"""
lxc_agent - Uzak MQTTS İstemcisi (Remote Cloud / Server MQTTS Client)
TLS 1.2/1.3, mTLS veya kullanıcı/şifre doğrulamalı uzak broker bağlantısı,
LWT (Last Will and Testament) ve downlink komut dinleme.
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore

from .circuit_breaker import CircuitBreaker
from .config import RemoteMqttConfig

logger = logging.getLogger("lxc_agent.remote_mqtt")


class RemoteMqttClient:
    """
    Bulut / Merkez sunucudaki MQTTS brokerına bağlanan uzak MQTT istemcisi.
    Circuit Breaker ile sunucu arızalarını ve zaman aşımlarını yönetir.
    """

    def __init__(
        self,
        config: RemoteMqttConfig,
        fleet_id: str = "fleet-default",
        vehicle_id: str = "NB800-001",
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.config = config
        self.fleet_id = fleet_id
        self.vehicle_id = vehicle_id

        self.client_id = config.client_id or f"{vehicle_id}-agent"
        self._connected = False
        self._lock = threading.Lock()
        self._client: Optional[Any] = None
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

        # Konu Kalıpları
        self.topic_base = f"fleet/{fleet_id}/vehicles/{vehicle_id}"
        self.topic_telemetry = f"{self.topic_base}/telemetry"
        self.topic_health = f"{self.topic_base}/health"
        self.topic_historical = f"{self.topic_base}/historical"
        self.topic_status = f"{self.topic_base}/status"
        self.topic_downlink_config = f"{self.topic_base}/config/set"
        self.topic_downlink_params = f"{self.topic_base}/params/set"

        # Downlink Callback Tanımları
        self.on_downlink_config: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_downlink_params: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_connection_change: Optional[Callable[[bool], None]] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Uzak MQTTS bağlantısını başlatır."""
        if not self.config.enabled:
            logger.info("Uzak MQTTS bağlantısı devre dışı bırakılmış (enabled=False).")
            return

        if mqtt is None:
            raise RuntimeError("paho-mqtt kütüphanesi bulunamadı.")

        with self._lock:
            if hasattr(mqtt, "CallbackAPIVersion"):
                self._client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self.client_id,
                    clean_session=False,
                )
            else:
                self._client = mqtt.Client(
                    client_id=self.client_id,
                    clean_session=False,
                )

            # Yetkilendirme (Username / Password)
            if self.config.username:
                self._client.username_pw_set(self.config.username, self.config.password)

            # TLS / mTLS Yapılandırması
            if self.config.use_tls:
                try:
                    self._client.tls_set(
                        ca_certs=self.config.ca_cert,
                        certfile=self.config.client_cert,
                        keyfile=self.config.client_key,
                        cert_reqs=ssl.CERT_REQUIRED if self.config.ca_cert else ssl.CERT_NONE,
                        tls_version=ssl.PROTOCOL_TLS_CLIENT,
                    )
                except Exception as e:
                    logger.warning("TLS ayarlanırken uyarı: %s. Varsayılan TLS bağlamı deneniyor.", e)
                    self._client.tls_set()

            # Last Will and Testament (LWT) - Beklenmeyen kopmada merkez uyarılır
            lwt_payload = json.dumps(
                {"status": "offline", "vehicle_id": self.vehicle_id, "timestamp": int(time.time())}
            )
            self._client.will_set(self.topic_status, lwt_payload, qos=1, retain=True)

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            logger.info("Uzak MQTTS brokerına bağlanılıyor: %s:%d", self.config.host, self.config.port)
            try:
                self._client.connect_async(self.config.host, self.config.port, keepalive=self.config.keepalive)
            except Exception as e:
                logger.warning("Uzak broker ilk bağlantı denemesi başarısız (%s), arka planda denenecek.", e)

            self._client.loop_start()

    def stop(self) -> None:
        """Uzak MQTTS istemcisini güvenle kapatır."""
        with self._lock:
            if self._client:
                # Çıkış öncesi offline durumu yayınla
                try:
                    offline_payload = json.dumps(
                        {"status": "offline", "vehicle_id": self.vehicle_id, "timestamp": int(time.time())}
                    )
                    self._client.publish(self.topic_status, offline_payload, qos=1, retain=True)
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception as e:
                    logger.debug("Remote MQTT kapatma hatası: %s", e)
                self._client = None
                self._connected = False
                logger.info("Uzak MQTTS istemcisi durduruldu.")

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            logger.info("Uzak MQTTS brokerına bağlandı (%s:%d)", self.config.host, self.config.port)
            self._connected = True
            self.circuit_breaker.record_success()

            # Online durumunu bildir
            online_payload = json.dumps(
                {"status": "online", "vehicle_id": self.vehicle_id, "timestamp": int(time.time())}
            )
            client.publish(self.topic_status, online_payload, qos=1, retain=True)

            # Downlink konularına abone ol
            client.subscribe([(self.topic_downlink_config, 1), (self.topic_downlink_params, 1)])
            logger.info("Uzak downlink konularına abone olundu: %s, %s", self.topic_downlink_config, self.topic_downlink_params)

            if self.on_connection_change:
                try:
                    self.on_connection_change(True)
                except Exception as e:
                    logger.error("Remote on_connection_change hatası: %s", e)
        else:
            logger.error("Uzak broker bağlantı hatası, RC: %d", rc)
            self._connected = False
            self.circuit_breaker.record_failure(f"Uzak broker bağlantı hatası RC={rc}")

    def _on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        self._connected = False
        logger.warning("Uzak broker bağlantısı koptu (RC: %d).", rc)
        if rc != 0:
            self.circuit_breaker.record_failure(f"Beklenmeyen soket kopması RC={rc}")
        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception as e:
                logger.error("Remote on_connection_change hatası: %s", e)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.warning("Uzak brokertan geçersiz JSON (Konu: %s): %s", topic, e)
            return

        if topic == self.topic_downlink_config and self.on_downlink_config:
            logger.info("Merkezden konfigürasyon emri geldi: %s", payload)
            self.on_downlink_config(payload)
        elif topic == self.topic_downlink_params and self.on_downlink_params:
            logger.info("Merkezden parametre güncelleme emri geldi: %s", payload)
            self.on_downlink_params(payload)

    def publish_live_telemetry(self, telemetry_data: Dict[str, Any], ack_timeout: float = 3.0) -> bool:
        """Canlı telemetri paketini merkeze QoS 1 ile gönderir ve ACK bekler."""
        return self._publish(self.topic_telemetry, telemetry_data, qos=1, timeout=ack_timeout)

    def publish_health(self, health_data: Dict[str, Any], ack_timeout: float = 3.0) -> bool:
        """Cihaz sağlık verisini merkeze gönderir."""
        return self._publish(self.topic_health, health_data, qos=1, timeout=ack_timeout)

    def publish_historical_batch(self, batch_records: List[Dict[str, Any]], ack_timeout: float = 5.0) -> bool:
        """Çevrimdışında depolanan geçmiş kayıt partisini merkeze gönderir ve teyit bekler."""
        payload = {
            "vehicle_id": self.vehicle_id,
            "count": len(batch_records),
            "sent_at": int(time.time()),
            "records": batch_records,
        }
        return self._publish(self.topic_historical, payload, qos=1, timeout=ack_timeout)

    def _publish(self, topic: str, data: Dict[str, Any], qos: int = 1, timeout: float = 3.0) -> bool:
        # Devre kesici kontrolü: Eğer sunucu çökmüşse veya time-out aşılmışsa sıfır gecikmeyle iptal et
        if not self.circuit_breaker.can_attempt():
            return False

        if not self._client or not self._connected:
            return False

        try:
            payload_str = json.dumps(data, ensure_ascii=False)
            res = self._client.publish(topic, payload_str, qos=qos)
            if res.rc != mqtt.MQTT_ERR_SUCCESS:
                self.circuit_breaker.record_failure(f"Paho publish hatası RC={res.rc}")
                return False

            if qos >= 1:
                # QoS 1: Karşı taraftan PUBACK yanıtının gelmesini bekle
                try:
                    res.wait_for_publish(timeout=timeout)
                    if res.is_published():
                        self.circuit_breaker.record_success()
                        return True
                    else:
                        self.circuit_breaker.record_failure(f"PUBACK zaman aşımı ({timeout} sn)")
                        return False
                except Exception as e:
                    self.circuit_breaker.record_failure(f"wait_for_publish hatası: {e}")
                    return False
            else:
                self.circuit_breaker.record_success()
                return True

        except Exception as e:
            logger.error("Uzak broker mesaj yayınlama hatası (%s): %s", topic, e)
            self.circuit_breaker.record_failure(f"Yayınlama istisnası: {e}")
            return False
