"""
lxc_agent - Yerel MQTT İstemcisi (Local Mosquitto Client)
Host (NRSW) üzerinde çalışan arena_agent (telemetry_daemon.are ve olay betikleri)
ile 192.168.100.1:1883 üzerinden haberleşir.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore

logger = logging.getLogger("lxc_agent.local_mqtt")

# Konu Sabitleri (Topic Constants)
TOPIC_TELEMETRY_GNSS = "local/telemetry/gnss"
TOPIC_TELEMETRY_SYSTEM = "local/telemetry/system"
TOPIC_EVENT_WAN = "local/event/wan"
TOPIC_EVENT_VPN = "local/event/vpn"
TOPIC_EVENT_GPS = "local/event/gps"
TOPIC_EVENT_TIME = "local/event/time"
TOPIC_EVENT_SYSTEM = "local/event/system"
TOPIC_PARAMS_STATUS = "local/arena/params/status"
TOPIC_CONFIG_RES = "local/cmd/config/res"

TOPIC_PARAMS_SET = "local/arena/params/set"
TOPIC_CONFIG_SET = "local/cmd/config/set"


def get_default_gateway() -> Optional[str]:
    """Linux /proc/net/route dosyasından varsayılan ağ geçidi (Gateway / Host) IP'sini okur."""
    try:
        with open("/proc/net/route", "r", encoding="ascii") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] == "00000000":
                    import socket
                    import struct
                    return socket.inet_ntoa(struct.pack("<L", int(parts[2], 16)))
    except Exception:
        pass
    return None


class LocalMqttClient:
    """
    Host (NRSW) Mosquitto brokerına bağlanan yerel MQTT istemcisi.
    """

    def __init__(
        self,
        host: str = "192.168.10.1",
        port: int = 1883,
        client_id: str = "lxc_telemetry_agent",
        keepalive: int = 60,
    ) -> None:
        # Otomatik ağ geçidi tespiti (Masabaşında 192.168.10.1, Sahada 192.168.100.1)
        if host in ("auto", "", "default"):
            detected_gw = get_default_gateway()
            self.host = detected_gw or "192.168.10.1"
            logger.info("Yerel ağ geçidi (Gateway) tespit edildi: %s", self.host)
        else:
            self.host = host

        self.port = port
        self.client_id = client_id
        self.keepalive = keepalive

        self._connected = False
        self._lock = threading.Lock()
        self._client: Optional[Any] = None

        # Olay Callback Tanımları
        self.on_gnss_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_system_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_wan_event_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_vpn_event_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_gps_event_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_time_sync_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_system_event_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_params_status_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_config_res_received: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_connection_change: Optional[Callable[[bool], None]] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """MQTT istemcisini başlatır ve arka plan döngüsünü açar."""
        if mqtt is None:
            raise RuntimeError("paho-mqtt kütüphanesi yüklü değil! 'apk add py3-paho-mqtt' veya 'pip install paho-mqtt'")

        with self._lock:
            # paho-mqtt v1 ve v2 uyumluluğu
            if hasattr(mqtt, "CallbackAPIVersion"):
                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.client_id,
                    clean_session=True,
                )
            else:
                self._client = mqtt.Client(
                    client_id=self.client_id,
                    clean_session=True,
                )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            logger.info("Yerel Mosquitto brokerına bağlanılıyor: %s:%d", self.host, self.port)
            try:
                self._client.connect_async(self.host, self.port, keepalive=self.keepalive)
            except Exception as e:
                logger.warning("Yerel broker ilk bağlantı denemesi başarısız (%s), arka planda yeniden denenecek.", e)

            self._client.loop_start()

    def stop(self) -> None:
        """MQTT istemcisini durdurur ve temizler."""
        with self._lock:
            if self._client:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception as e:
                    logger.debug("Local MQTT durdurma hatası: %s", e)
                self._client = None
                self._connected = False
                logger.info("Yerel MQTT istemcisi durduruldu.")

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            logger.info("Yerel Mosquitto brokerına başarıyla bağlandı (%s:%d)", self.host, self.port)
            self._connected = True

            # arena_agent_mqtt.txt abonelik şablonu
            subscriptions = [
                ("local/telemetry/#", 0),
                ("local/event/#", 1),
                (TOPIC_PARAMS_STATUS, 0),
                (TOPIC_CONFIG_RES, 1),
            ]
            client.subscribe(subscriptions)
            logger.info("Yerel konulara abone olundu: local/telemetry/#, local/event/#, %s, %s", TOPIC_PARAMS_STATUS, TOPIC_CONFIG_RES)

            if self.on_connection_change:
                try:
                    self.on_connection_change(True)
                except Exception as e:
                    logger.error("on_connection_change hatası: %s", e)
        else:
            logger.error("Yerel broker bağlantı hatası, RC: %d", rc)
            self._connected = False

    def _on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        self._connected = False
        logger.warning("Yerel Mosquitto bağlantısı koptu (RC: %d). Yeniden bağlanılıyor...", rc)
        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception as e:
                logger.error("on_connection_change hatası: %s", e)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        topic = msg.topic
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
        except Exception as e:
            logger.warning("Ayrıştırılamayan JSON mesajı (Konu: %s): %s", topic, e)
            return

        try:
            if topic == TOPIC_TELEMETRY_GNSS:
                if self.on_gnss_received:
                    self.on_gnss_received(data)
            elif topic == TOPIC_TELEMETRY_SYSTEM:
                if self.on_system_received:
                    self.on_system_received(data)
            elif topic == TOPIC_EVENT_WAN:
                logger.info("WAN Olayı Alındı: %s", data)
                if self.on_wan_event_received:
                    self.on_wan_event_received(data)
            elif topic == TOPIC_EVENT_VPN:
                logger.info("VPN Olayı Alındı: %s", data)
                if self.on_vpn_event_received:
                    self.on_vpn_event_received(data)
            elif topic == TOPIC_EVENT_GPS:
                logger.info("GPS Olayı Alındı: %s", data)
                if self.on_gps_event_received:
                    self.on_gps_event_received(data)
            elif topic == TOPIC_EVENT_TIME:
                logger.info("Zaman Senkronizasyon Olayı Alındı: %s", data)
                if self.on_time_sync_received:
                    self.on_time_sync_received(data)
            elif topic == TOPIC_EVENT_SYSTEM:
                logger.info("Sistem Olayı Alındı: %s", data)
                if self.on_system_event_received:
                    self.on_system_event_received(data)
            elif topic == TOPIC_PARAMS_STATUS:
                logger.info("Arena Parametre Durumu (ACK): %s", data)
                if self.on_params_status_received:
                    self.on_params_status_received(data)
            elif topic == TOPIC_CONFIG_RES:
                logger.info("Router Konfigürasyon Sonucu: %s", data)
                if self.on_config_res_received:
                    self.on_config_res_received(data)
            else:
                logger.debug("Bilinmeyen yerel konu: %s -> %s", topic, data)
        except Exception as e:
            logger.error("Mesaj işlenirken hata oluştu (Konu: %s): %s", topic, e, exc_info=True)

    def publish_params_set(
        self,
        publish_interval_moving_sec: Optional[int] = None,
        publish_interval_idle_sec: Optional[int] = None,
        speed_threshold_kmh: Optional[float] = None,
        max_storage_mb: Optional[int] = None,
    ) -> bool:
        """
        telemetry_daemon.are çalışma frekansını çalışma anında değiştirir (Hot-Reload).
        Reboot sonrası kalıcılık için QoS 1 ve Retain: True kullanılır.
        """
        payload: Dict[str, Any] = {}
        if publish_interval_moving_sec is not None:
            payload["publish_interval_moving_sec"] = int(publish_interval_moving_sec)
        if publish_interval_idle_sec is not None:
            payload["publish_interval_idle_sec"] = int(publish_interval_idle_sec)
        if speed_threshold_kmh is not None:
            payload["speed_threshold_kmh"] = float(speed_threshold_kmh)
        if max_storage_mb is not None:
            payload["max_storage_mb"] = int(max_storage_mb)

        if not payload:
            logger.warning("publish_params_set: Gönderilecek geçerli alan yok.")
            return False

        return self._publish_json(TOPIC_PARAMS_SET, payload, qos=1, retain=True)

    def publish_config_set(self, req_id: str, key: str, value: str) -> bool:
        """
        Router NRSW ayarını değiştirmek için telemetry_daemon.are'a emir gönderir.
        """
        payload = {
            "req_id": req_id,
            "key": key,
            "value": value,
        }
        return self._publish_json(TOPIC_CONFIG_SET, payload, qos=1, retain=False)

    def _publish_json(self, topic: str, data: Dict[str, Any], qos: int = 1, retain: bool = False) -> bool:
        if not self._client or not self._connected:
            logger.warning("Yerel broker bağlı değil. Mesaj gönderilemedi: %s", topic)
            return False
        try:
            payload_str = json.dumps(data, ensure_ascii=False)
            res = self._client.publish(topic, payload_str, qos=qos, retain=retain)
            return res.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error("Mesaj yayınlama hatası (%s): %s", topic, e)
            return False
