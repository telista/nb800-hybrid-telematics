"""
lxc_agent - Ana İş Mantığı ve Orkestrasyon Motoru (Core Telemetry Engine)
Yerel ve uzak MQTT olaylarını koordine eder, telemetriyi zenginleştirir,
Store-and-Forward ve 1970 zaman damgası düzeltme süreçlerini yönetir.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .config import AgentConfig
from .local_mqtt import LocalMqttClient
from .remote_mqtt import RemoteMqttClient
from .storage import StoreAndForwardQueue
from .web_server import WebDiagnosticsServer

logger = logging.getLogger("lxc_agent.engine")


def get_container_memory_metrics() -> Dict[str, Any]:
    """
    Linux cgroup bellek denetleyicisinden konteynerin anlık gerçek RAM kullanımını
    ve tavan kotasını (limit) okur. memory.stat içerisindeki gerçek anonim RSS
    değerini tercih ederek kernel dosya önbelleğinin (page cache) kullanım yüzdesini
    yapay olarak şişirmesini engeller.
    """
    try:
        # cgroup v1 yolları (NetModule NB800 NRSW 5.0 standartı)
        usage_path = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
        limit_path = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
        stat_path = "/sys/fs/cgroup/memory/memory.stat"

        # cgroup v2 yedek yolları
        if not os.path.exists(usage_path) and os.path.exists("/sys/fs/cgroup/memory.current"):
            usage_path = "/sys/fs/cgroup/memory.current"
            limit_path = "/sys/fs/cgroup/memory.max"
            stat_path = "/sys/fs/cgroup/memory.stat"

        if os.path.exists(usage_path) and os.path.exists(limit_path):
            with open(usage_path, "r") as f:
                used_bytes = int(f.read().strip())
            with open(limit_path, "r") as f:
                limit_raw = f.read().strip()
                limit_bytes = int(limit_raw) if limit_raw != "max" else 0

            # Gerçek süreç bellek tüketimini (RSS) memory.stat'tan oku
            if os.path.exists(stat_path):
                try:
                    with open(stat_path, "r") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) == 2:
                                if parts[0] == "total_rss":
                                    used_bytes = int(parts[1])
                                    break
                                elif parts[0] in ("rss", "anon"):
                                    used_bytes = int(parts[1])
                except Exception as stat_err:
                    logger.debug("memory.stat okuma uyarısı: %s", stat_err)

            # 2^62 gibi sınırsız tavan değerlerini ele
            if 0 < limit_bytes < (1024**4):
                used_mb = round(used_bytes / (1024 * 1024), 1)
                limit_mb = round(limit_bytes / (1024 * 1024), 0)
                pct = round((used_bytes / limit_bytes) * 100.0, 1)
                return {
                    "memory_usage_pct": pct,
                    "ram_used_mb": used_mb,
                    "ram_limit_mb": int(limit_mb),
                    "ram_text": f"{used_mb} MB / {int(limit_mb)} MB (%{pct})",
                }
    except Exception as e:
        logger.debug("cgroup bellek okuma hatası: %s", e)

    return {
        "memory_usage_pct": 0.0,
        "ram_used_mb": 0.0,
        "ram_limit_mb": 0,
        "ram_text": "-",
    }


class TelemetryEngine:
    """
    Tüm veri akışını, durum makinelerini (WAN, GPS, Zaman) ve çevrimdışı
    tampon yönetimini yöneten ana motor.
    """

    def __init__(
        self,
        config: AgentConfig,
        storage: Optional[StoreAndForwardQueue] = None,
        local_mqtt: Optional[LocalMqttClient] = None,
        remote_mqtt: Optional[RemoteMqttClient] = None,
    ) -> None:
        self.config = config
        self.storage = storage or StoreAndForwardQueue(
            db_path=config.storage.db_path,
            max_storage_mb=config.storage.max_storage_mb,
            flush_interval_sec=config.storage.flush_interval_sec,
        )

        self.local_mqtt = local_mqtt or LocalMqttClient(
            host=config.local_mqtt.host,
            port=config.local_mqtt.port,
            client_id=config.local_mqtt.client_id,
            keepalive=config.local_mqtt.keepalive,
        )

        self.remote_mqtt = remote_mqtt or RemoteMqttClient(
            config=config.remote_mqtt,
            fleet_id=config.device.fleet_id,
            vehicle_id=config.device.vehicle_id,
        )

        # Durum Değişkenleri
        self.wan_state = "unknown"  # "up", "down", "unknown"
        self.vpn_state = "unknown"  # "up", "down", "unknown"
        self.gps_state = "unknown"  # "up", "down", "unknown"
        # NB800 donanımında RTC pili olmadığı için açılışta 1970 olabilir.
        # Eğer sistem saati zaten 2020 sonrasına ayarlanmışsa senkronize başlar.
        self.time_synced = time.time() > 1577836800
        self._lock = threading.Lock()

        # Son alınan telemetri önbelleği
        self._last_system_data: Dict[str, Any] = {}
        self._last_gnss_data: Dict[str, Any] = {}

        # Hücresel Veri & Maliyet Optimizasyonu
        opt_cfg = getattr(config, "optimization", None)
        self.data_optimization_enabled: bool = getattr(opt_cfg, "enabled", True) if opt_cfg else True
        self.health_interval_sec: int = getattr(opt_cfg, "health_interval_sec", 60) if opt_cfg else 60
        self.publish_health: bool = getattr(opt_cfg, "publish_health", False) if opt_cfg else False
        self._last_health_publish_time: float = 0.0

        default_moving = 5 if self.data_optimization_enabled else 2
        default_idle = 60 if self.data_optimization_enabled else 30

        # Arena parametreleri önbelleği (telemetry_daemon.are)
        self.arena_params: Dict[str, Any] = {
            "publish_interval_moving_sec": default_moving,
            "publish_interval_idle_sec": default_idle,
            "speed_threshold_kmh": 5.0,
            "max_storage_mb": getattr(config.storage, "max_storage_mb", 50),
            "status": "initial",
        }

        # Web Teşhis ve İndirme Sunucusu (Port 8080)
        self.web_server: Optional[WebDiagnosticsServer] = None
        if getattr(config, "web_enabled", True):
            self.web_server = WebDiagnosticsServer(
                engine=self, port=getattr(config, "web_port", 8080)
            )

        # Arka plan iş parçacıkları
        self._running = False
        self._drain_thread: Optional[threading.Thread] = None
        self._drain_event = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None

        # Yerel MQTT Callback Bağlantıları
        self._bind_callbacks()

    def _bind_callbacks(self) -> None:
        self.local_mqtt.on_gnss_received = self.handle_gnss
        self.local_mqtt.on_system_received = self.handle_system
        self.local_mqtt.on_wan_event_received = self.handle_wan_event
        self.local_mqtt.on_vpn_event_received = self.handle_vpn_event
        self.local_mqtt.on_gps_event_received = self.handle_gps_event
        self.local_mqtt.on_time_sync_received = self.handle_time_sync
        self.local_mqtt.on_config_res_received = self.handle_config_res
        self.local_mqtt.on_params_status_received = self.handle_params_status
        self.local_mqtt.on_connection_change = self.handle_local_connection_change

        # Uzaktan merkeze gelen downlink komutlarını yerel broker'a bağla
        self.remote_mqtt.on_downlink_config = self.handle_downlink_config
        self.remote_mqtt.on_downlink_params = self.handle_downlink_params
        self.remote_mqtt.on_connection_change = self.handle_remote_connection_change

    def start(self) -> None:
        """Motoru, yerel/uzak MQTT istemcilerini, Web sunucusunu ve arka plan işçilerini başlatır."""
        logger.info("TelemetryEngine başlatılıyor...")
        self._running = True

        # Yerel istemciyi başlat
        self.local_mqtt.start()

        # Uzak istemciyi başlat (eğer etkinse)
        if self.config.remote_mqtt.enabled:
            self.remote_mqtt.start()

        # Web Teşhis ve İndirme Sunucusunu başlat
        if self.web_server:
            self.web_server.start()

        # Periyodik Flush İşçisi (Flash ömrünü korumak için)
        self._flush_thread = threading.Thread(target=self._flush_worker, daemon=True, name="FlushWorker")
        self._flush_thread.start()

        # Kuyruk Boşaltma (Drain Worker) İşçisi
        self._drain_thread = threading.Thread(target=self._drain_worker, daemon=True, name="DrainWorker")
        self._drain_thread.start()

        if self.time_synced:
            patched = self.storage.back_patch_timestamps(int(time.time()))
            if patched > 0:
                logger.info("Açılışta bekleyen %d kaydın zaman damgası senkronize edildi.", patched)

        logger.info("TelemetryEngine aktif.")

    def stop(self) -> None:
        """Tüm servisleri düzenli şekilde durdurur."""
        logger.info("TelemetryEngine durduruluyor...")
        self._running = False
        self._drain_event.set()

        if self.web_server:
            self.web_server.stop()

        self.local_mqtt.stop()
        if self.config.remote_mqtt.enabled:
            self.remote_mqtt.stop()

        if self._drain_thread and self._drain_thread.is_alive():
            self._drain_thread.join(timeout=2.0)

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)

        self.storage.close()
        logger.info("TelemetryEngine başarıyla kapatıldı.")

    # -------------------------------------------------------------------------
    # TELEMETRİ İŞLEME VE ZENGİNLEŞTİRME
    # -------------------------------------------------------------------------

    def _check_and_mark_time_synced(self, ts: int) -> None:
        """Gelen telemetri veya sistem zaman damgasından zaman senkronunu kontrol eder ve günceller."""
        if not self.time_synced and ts > 1577836800:
            self.time_synced = True
            logger.info("Geçerli sistem saati tespit edildi (%d). Zaman senkronize olarak işaretleniyor...", ts)
            patched = self.storage.back_patch_timestamps(ts)
            if patched > 0:
                logger.info("Zaman yamalaması tamamlandı: %d kayıt güncellendi.", patched)

    def handle_gnss(self, data: Dict[str, Any]) -> None:
        """
        'local/telemetry/gnss' mesajı geldiğinde çalışır.
        En son sistem durumuyla harmanlayarak birleşik zenginleştirilmiş paket üretir.
        """
        with self._lock:
            self._last_gnss_data = data
            ts = data.get("timestamp", int(time.time()))
            self._check_and_mark_time_synced(ts)

            # Eğer GPS down durumundaysa veya fix yoksa bayrağı düzelt
            if self.gps_state == "down":
                data["fix"] = False

            payload = self._build_enriched_packet("telemetry", gnss=data, system=self._last_system_data)

        self._route_packet("telemetry", payload, ts)

    def handle_system(self, data: Dict[str, Any]) -> None:
        """'local/telemetry/system' mesajı geldiğinde çalışır."""
        with self._lock:
            # Gerçek cgroup konteyner bellek metriklerini ekle
            mem_info = get_container_memory_metrics()
            if mem_info["memory_usage_pct"] > 0:
                data["memory_usage_pct"] = mem_info["memory_usage_pct"]
                data["ram_used_mb"] = mem_info["ram_used_mb"]
                data["ram_limit_mb"] = mem_info["ram_limit_mb"]
                data["ram_text"] = mem_info["ram_text"]

            self._last_system_data = data
            if data.get("imei"):
                real_imei = str(data["imei"]).strip()
                if real_imei and real_imei != self.config.device.imei:
                    logger.info("Gerçek GSM Modem IMEI güncellendi: %s -> %s", self.config.device.imei, real_imei)
                    self.config.device.imei = real_imei
            ts = data.get("timestamp", int(time.time()))
            # Yedek Ağ Durumu Çıkarımı: Olay betikleri tetiklenmemiş olsa bile
            # sistem telemetrisindeki vpn_connected ve sinyal durumundan ağ durumunu güncelle
            if "vpn_connected" in data:
                if data["vpn_connected"] and self.vpn_state != "up":
                    old_vpn = self.vpn_state
                    self.vpn_state = "up"
                    logger.info("VPN durumu telemetriden algılandı: %s -> up", old_vpn)
                    self._drain_event.set()
                elif not data["vpn_connected"] and self.vpn_state == "up":
                    self.vpn_state = "down"
                    logger.warning("VPN durumu telemetriden algılandı: down")

            rssi = data.get("wwan_signal_rssi", 0)
            if rssi and rssi > -110 and rssi != 99 and self.wan_state == "unknown":
                self.wan_state = "up"
                logger.info("Hücresel WAN durumu telemetriden algılandı: unknown -> up (RSSI: %d dBm)", rssi)
                self._drain_event.set()

            # Optimizasyon Denetimi:
            # Canlı telemetri paketi (gnss + system) zaten sistem durumunu merkeze iletmektedir.
            # publish_health kapalıysa (varsayılan: False), mükerrer health mesajı üretilmez.
            # publish_health açık ise:
            #   Optimizasyon etkinse sadece bağımsız kalp atışı aralığı (health_interval_sec) dolduğunda merkeze basılır.
            #   Optimizasyon devre dışıysa (sınırsız bütçe modu), her sistem mesajında merkeze basılır.
            now = time.time()
            should_publish_health = (
                self.publish_health
                and (
                    not self.data_optimization_enabled
                    or (now - self._last_health_publish_time >= self.health_interval_sec)
                )
            )

            if should_publish_health:
                self._last_health_publish_time = now
                payload = self._build_enriched_packet("health", system=data)
            else:
                payload = None

        # Cihaz sağlık bilgisini yönlendir (varsa)
        if payload is not None:
            self._route_packet("health", payload, ts)

    def _build_enriched_packet(
        self,
        packet_type: str,
        gnss: Optional[Dict[str, Any]] = None,
        system: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Araç kimlikleri ve durum bilgisiyle zenginleştirilmiş telemetri paketi üretir."""
        packet: Dict[str, Any] = {
            "type": packet_type,
            "vehicle_id": self.config.device.vehicle_id,
            "fleet_id": self.config.device.fleet_id,
            "wan_state": self.wan_state,
            "vpn_state": self.vpn_state,
            "gps_state": self.gps_state,
            "time_synced": self.time_synced,
            "timestamp": int(time.time()),
        }
        if self.config.device.imei:
            packet["imei"] = self.config.device.imei

        if gnss:
            packet["gnss"] = gnss
            if "timestamp" in gnss:
                packet["timestamp"] = gnss["timestamp"]

        if system:
            # VPN Durumu Tutarlılığı: Eğer tünel UP ise sistem objesi içindeki bayrakları ve IP'yi düzelt
            if self.vpn_state == "up":
                system["vpn_connected"] = True
                if not system.get("vpn_ip"):
                    system["vpn_ip"] = "10.8.0.4"
            # Gerçek cgroup konteyner bellek metriklerini ekle
            if "ram_text" not in system:
                mem_info = get_container_memory_metrics()
                if mem_info["memory_usage_pct"] > 0:
                    system["memory_usage_pct"] = mem_info["memory_usage_pct"]
                    system["ram_used_mb"] = mem_info["ram_used_mb"]
                    system["ram_limit_mb"] = mem_info["ram_limit_mb"]
                    system["ram_text"] = mem_info["ram_text"]
            packet["system"] = system

        return packet

    def _route_packet(self, category: str, payload: Dict[str, Any], timestamp: int) -> None:
        """
        Paketin merkeze canlı mı gönderileceğine yoksa çevrimdışı kuyruğa mı
        yazılacağına karar verir (Zero-Latency Switching).
        """
        can_send_live = (
            self.wan_state != "down"
            and self.vpn_state != "down"
            and self.config.remote_mqtt.enabled
            and self.remote_mqtt.is_connected
            and (
                getattr(self.remote_mqtt, "circuit_breaker", None) is None
                or self.remote_mqtt.circuit_breaker.can_attempt()
            )
        )

        if can_send_live:
            # Canlı aktarımı dene
            success = False
            if category == "telemetry":
                success = self.remote_mqtt.publish_live_telemetry(payload)
            elif category == "health":
                success = self.remote_mqtt.publish_health(payload)

            if success:
                return

        # Canlı gönderilemedi, devre kesici açık veya sunucu/WAN/VPN erişilemez -> Store-and-Forward
        self.storage.enqueue(
            topic=category,
            payload=payload,
            timestamp=timestamp,
            time_synced=self.time_synced,
        )

    # -------------------------------------------------------------------------
    # OLAY İŞLEYİCİLERİ (EVENTS)
    # -------------------------------------------------------------------------

    def handle_wan_event(self, data: Dict[str, Any]) -> None:
        """
        'local/event/wan' olayını anında yakalar.
        'down' anında hemen çevrimdışı depolamaya kilitlenir.
        'up' anında ise kuyruk boşaltma işçisini uyandırır.
        """
        state = str(data.get("state", "")).lower()
        old_state = self.wan_state
        self.wan_state = state
        logger.info("WAN Durum Değişikliği: %s -> %s", old_state, state)

        if state == "up":
            # İnternet geldi! Kuyruğu boşaltmak için işçiyi uyandır
            self._drain_event.set()
        elif state == "down":
            logger.warning("Hücresel internet kesildi! Veriler çevrimdışı SQLite deposuna yazılıyor.")

    def handle_vpn_event(self, data: Dict[str, Any]) -> None:
        """
        'local/event/vpn' olayını yakalar (401: openvpn-up, 402: openvpn-down).
        VPN koptuğunda uzak MQTT'ye erişilemeyeceği için canlı gönderimi durdurur
        ve tüm verileri SQLite Store-and-Forward deposuna yönlendirir.
        VPN yeniden bağlandığında ise tahliye işçisini (drain worker) uyandırır.
        """
        state = str(data.get("state", "")).lower()
        old_state = self.vpn_state
        self.vpn_state = state
        logger.info("VPN Durum Değişikliği: %s -> %s (Arayüz: %s)", old_state, state, data.get("interface", "tun0"))

        if state == "up":
            logger.info("VPN tüneli kuruldu. Kuyruk boşaltma (Drain) tetikleniyor...")
            self._drain_event.set()
        elif state == "down":
            logger.warning("VPN tüneli koptu! Uzak telemetri akışı durduruldu, veriler çevrimdışı SQLite deposuna yönlendiriliyor.")

    def handle_gps_event(self, data: Dict[str, Any]) -> None:
        """'local/event/gps' GPS kilitlenme/kayıp olayını yakalar."""
        state = str(data.get("state", "")).lower()
        self.gps_state = state
        logger.info("GPS Durum Değişikliği: %s (Uydular: %s)", state, data.get("satellites", 0))

    def handle_time_sync(self, data: Dict[str, Any]) -> None:
        """
        'local/event/time' (508: system-time-updated) ulaştığında çalışır.
        1970 yılıyla kaydedilmiş eski verileri geriye dönük gerçek zamanla günceller.
        """
        ts = data.get("timestamp")
        if ts and int(ts) > 1577836800:
            self.time_synced = True
            logger.info("Sistem saati senkronize edildi: %d. Timestamp Back-Patching başlatılıyor...", ts)
            patched = self.storage.back_patch_timestamps(int(ts))
            logger.info("Zaman yamalaması tamamlandı: %d kayıt güncellendi.", patched)

    def handle_system_event(self, data: Dict[str, Any]) -> None:
        """'local/event/system' açılış (startup) olayını yakalar."""
        logger.info("Host açılış olayı: %s", data)

    def handle_config_res(self, data: Dict[str, Any]) -> None:
        """telemetry_daemon.are'dan gelen router ayar uygulama sonucunu yakalar."""
        logger.info("Konfigürasyon yanıtı (Host -> LXC): %s", data)

    def handle_local_connection_change(self, connected: bool) -> None:
        """Yerel Mosquitto broker bağlantı durumu değiştiğinde tetiklenir."""
        logger.info("Yerel MQTT broker bağlantı durumu: %s", "Bağlandı" if connected else "Koptu")
        if connected:
            # Açılışta veya yeniden bağlanmada optimizasyon moduna göre Arena frekansını senkronize et
            if self.data_optimization_enabled:
                self.update_arena_params(publish_interval_moving_sec=5, publish_interval_idle_sec=60)
            else:
                self.update_arena_params(publish_interval_moving_sec=2, publish_interval_idle_sec=30)

    def handle_params_status(self, data: Dict[str, Any]) -> None:
        """telemetry_daemon.are'dan gelen parametre ACK mesajını yakalar."""
        with self._lock:
            self.arena_params.update(data)
        logger.info("Arena parametre onayı (Host -> LXC): %s", data)

        # Eğer Tasarruf Modu etkinse ve Arena henüz 5s / 60s'e geçmemişse otomatik senkronize et
        if self.data_optimization_enabled:
            moving = data.get("publish_interval_moving_sec")
            idle = data.get("publish_interval_idle_sec")
            if moving != 5 or idle != 60:
                logger.info("Tasarruf Modu etkin fakat Arena frekansı %ss / %ss; 5s / 60s olarak eşitleniyor...", moving, idle)
                self.update_arena_params(publish_interval_moving_sec=5, publish_interval_idle_sec=60)

    # -------------------------------------------------------------------------
    # UZAKTAN GELEN (DOWNLINK) KOMUTLAR
    # -------------------------------------------------------------------------

    def handle_downlink_config(self, payload: Dict[str, Any]) -> None:
        """Merkezden gelen router ayarını yerel broker üzerinden NRSW'ye iletir."""
        req_id = payload.get("req_id", f"req-{int(time.time())}")
        key = payload.get("key", "")
        value = payload.get("value", "")
        if key:
            logger.info("Merkezden gelen konfigürasyon NRSW'ye iletiliyor: %s=%s (Req: %s)", key, value, req_id)
            self.local_mqtt.publish_config_set(req_id, key, value)

    def handle_downlink_params(self, payload: Dict[str, Any]) -> None:
        """Merkezden gelen telemetri parametrelerini telemetry_daemon.are'a iletir."""
        logger.info("Merkezden gelen telemetri parametreleri uygulanıyor: %s", payload)
        self.local_mqtt.publish_params_set(
            publish_interval_moving_sec=payload.get("publish_interval_moving_sec"),
            publish_interval_idle_sec=payload.get("publish_interval_idle_sec"),
            speed_threshold_kmh=payload.get("speed_threshold_kmh"),
            max_storage_mb=payload.get("max_storage_mb"),
        )

    def handle_remote_connection_change(self, connected: bool) -> None:
        if connected:
            logger.info("Uzak broker bağlantısı sağlandı. Kuyruk boşaltma tetikleniyor...")
            self._drain_event.set()

    # -------------------------------------------------------------------------
    # ARKA PLAN İŞÇİLERİ (WORKERS)
    # -------------------------------------------------------------------------

    def _flush_worker(self) -> None:
        """Periyodik olarak uncommitted SQLite verilerini diske flush eder."""
        interval = max(1.0, self.config.storage.flush_interval_sec)
        while self._running:
            time.sleep(interval)
            try:
                self.storage.flush()
            except Exception as e:
                logger.error("Periyodik flush hatası: %s", e)

    def _drain_worker(self) -> None:
        """
        İnternet bağlantısı ve uzak broker aktif olduğunda
        çevrimdışında bekleyen geçmiş verileri partiler halinde merkeze boşaltır (Drain).
        """
        batch_size = max(5, self.config.storage.batch_size)
        drain_interval = max(0.2, self.config.storage.drain_interval_sec)

        while self._running:
            # WAN UP, Uzak broker bağlı ve Devre Kesici izin veriyor mu?
            can_drain = (
                self.wan_state == "up"
                and self.config.remote_mqtt.enabled
                and self.remote_mqtt.is_connected
                and (
                    getattr(self.remote_mqtt, "circuit_breaker", None) is None
                    or self.remote_mqtt.circuit_breaker.can_attempt()
                )
            )

            if not can_drain:
                # Bağlantı veya devre kesicinin test aşamasına geçmesini bekle
                self._drain_event.wait(timeout=3.0)
                self._drain_event.clear()
                continue

            records = self.storage.fetch_batch(limit=batch_size)
            if not records:
                # Kuyruk boş, yeni veri veya olay bekle
                self._drain_event.wait(timeout=5.0)
                self._drain_event.clear()
                continue

            # Batch paketini hazırla ve uzak brokera gönder
            ids = [r["id"] for r in records]
            formatted_batch = [
                {
                    "topic": r["topic"],
                    "timestamp": r["timestamp"],
                    "data": r["payload"],
                }
                for r in records
            ]

            success = self.remote_mqtt.publish_historical_batch(formatted_batch)
            if success:
                deleted = self.storage.acknowledge_batch(ids)
                logger.info("Kuyruk boşaltıldı: %d kayıt merkeze iletildi ve silindi.", deleted)
                time.sleep(drain_interval)
            else:
                logger.warning("Kuyruk partisi merkeze iletilemedi, yeniden denenecek...")
                time.sleep(2.0)

    def update_device_identity(self, vehicle_id: str, fleet_id: str) -> bool:
        """
        Araç Kimliğini ve Filo ID'sini çalışma zamanında günceller ve
        kalıcı olarak yapılandırma dosyasına (config.json) kaydeder.
        """
        v_id = vehicle_id.strip()
        f_id = fleet_id.strip()
        if not v_id or not f_id:
            logger.warning("Geçersiz araç kimliği veya filo ID: '%s', '%s'", vehicle_id, fleet_id)
            return False

        with self._lock:
            self.config.device.vehicle_id = v_id
            self.config.device.fleet_id = f_id

            if self.remote_mqtt:
                self.remote_mqtt.vehicle_id = v_id
                self.remote_mqtt.fleet_id = f_id

            # Yapılandırma dosyasını güncelle
            saved = self.config.save()
            logger.info("Araç kimliği güncellendi: Araç=%s, Filo=%s (Kaydedildi: %s)", v_id, f_id, saved)
            return True

    def update_arena_params(
        self,
        publish_interval_moving_sec: Optional[int] = None,
        publish_interval_idle_sec: Optional[int] = None,
        speed_threshold_kmh: Optional[float] = None,
        max_storage_mb: Optional[int] = None,
    ) -> bool:
        """
        telemetry_daemon.are çalışma frekansını ve eşiklerini yerel Mosquitto
        üzerinden günceller (Hot-Reload) ve kalıcı retain bayrağı ile yayınlar.
        """
        sent = self.local_mqtt.publish_params_set(
            publish_interval_moving_sec=publish_interval_moving_sec,
            publish_interval_idle_sec=publish_interval_idle_sec,
            speed_threshold_kmh=speed_threshold_kmh,
            max_storage_mb=max_storage_mb,
        )
        if sent:
            with self._lock:
                if publish_interval_moving_sec is not None:
                    self.arena_params["publish_interval_moving_sec"] = int(publish_interval_moving_sec)
                if publish_interval_idle_sec is not None:
                    self.arena_params["publish_interval_idle_sec"] = int(publish_interval_idle_sec)
                if speed_threshold_kmh is not None:
                    self.arena_params["speed_threshold_kmh"] = float(speed_threshold_kmh)
                if max_storage_mb is not None:
                    self.arena_params["max_storage_mb"] = int(max_storage_mb)
            logger.info("Arena parametre güncellemesi yerel brokera iletildi: %s", self.arena_params)
        return sent

    def set_data_optimization(
        self,
        enabled: bool,
        health_interval_sec: Optional[int] = None,
        publish_health: Optional[bool] = None,
    ) -> bool:
        """
        Hücresel veri ve maliyet optimizasyonunu çalışma zamanında açar/kapatır
        ve yapılandırma dosyasına (config.json) kalıcı olarak kaydeder.
        """
        with self._lock:
            self.data_optimization_enabled = bool(enabled)
            if health_interval_sec is not None and int(health_interval_sec) > 0:
                self.health_interval_sec = int(health_interval_sec)
            if publish_health is not None:
                self.publish_health = bool(publish_health)

            if hasattr(self.config, "optimization"):
                self.config.optimization.enabled = self.data_optimization_enabled
                self.config.optimization.health_interval_sec = self.health_interval_sec
                self.config.optimization.publish_health = self.publish_health

            saved = self.config.save()

        # Arena çalışma frekansını mod ile senkronize et (Hot-Reload)
        if self.data_optimization_enabled:
            self.update_arena_params(publish_interval_moving_sec=5, publish_interval_idle_sec=60)
        else:
            self.update_arena_params(publish_interval_moving_sec=2, publish_interval_idle_sec=30)

        return True
