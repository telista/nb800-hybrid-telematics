"""
lxc_agent - Yapılandırma Yöneticisi (Configuration Manager)
JSON yapılandırma dosyası ve ortam değişkenleri (Environment Variables) desteği.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("lxc_agent.config")


@dataclass
class LocalMqttConfig:
    host: str = "auto"
    port: int = 1883
    client_id: str = "lxc_telemetry_agent"
    keepalive: int = 60


@dataclass
class RemoteMqttConfig:
    enabled: bool = False
    host: str = "mqtt.example.com"
    port: int = 8883
    client_id: str = ""
    keepalive: int = 60
    username: str = ""
    password: str = ""
    use_tls: bool = True
    ca_cert: Optional[str] = None
    client_cert: Optional[str] = None
    client_key: Optional[str] = None


@dataclass
class StorageConfig:
    db_path: str = "/var/lib/lxc_agent/store_and_forward.db"
    max_storage_mb: int = 50
    batch_size: int = 50
    flush_interval_sec: float = 3.0
    drain_interval_sec: float = 1.0


@dataclass
class DeviceConfig:
    fleet_id: str = "fleet-default"
    vehicle_id: str = "NB800-001"
    imei: str = ""


@dataclass
class WebConfig:
    enabled: bool = True
    port: int = 8080
    auth_enabled: bool = True
    username: str = "admin"
    password: str = "admin"


@dataclass
class OptimizationConfig:
    enabled: bool = True
    health_interval_sec: int = 60
    publish_health: bool = False


@dataclass
class AgentConfig:
    log_level: str = "INFO"
    config_path: Optional[str] = None
    web: WebConfig = field(default_factory=WebConfig)
    local_mqtt: LocalMqttConfig = field(default_factory=LocalMqttConfig)
    remote_mqtt: RemoteMqttConfig = field(default_factory=RemoteMqttConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)

    # Geriye dönük uyumluluk (backward compatibility)
    @property
    def web_enabled(self) -> bool:
        return self.web.enabled

    @web_enabled.setter
    def web_enabled(self, val: bool) -> None:
        self.web.enabled = val

    @property
    def web_port(self) -> int:
        return self.web.port

    @web_port.setter
    def web_port(self, val: int) -> None:
        self.web.port = val

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentConfig:
        config = cls()
        if "log_level" in data:
            config.log_level = str(data["log_level"]).upper()

        if "web" in data and isinstance(data["web"], dict):
            wb = data["web"]
            config.web = WebConfig(
                enabled=bool(wb.get("enabled", config.web.enabled)),
                port=int(wb.get("port", config.web.port)),
                auth_enabled=bool(wb.get("auth_enabled", config.web.auth_enabled)),
                username=str(wb.get("username", config.web.username)),
                password=str(wb.get("password", config.web.password)),
            )
        else:
            if "web_enabled" in data:
                config.web.enabled = bool(data["web_enabled"])
            if "web_port" in data:
                config.web.port = int(data["web_port"])

        if "local_mqtt" in data and isinstance(data["local_mqtt"], dict):
            lm = data["local_mqtt"]
            config.local_mqtt = LocalMqttConfig(
                host=lm.get("host", config.local_mqtt.host),
                port=int(lm.get("port", config.local_mqtt.port)),
                client_id=lm.get("client_id", config.local_mqtt.client_id),
                keepalive=int(lm.get("keepalive", config.local_mqtt.keepalive)),
            )

        if "remote_mqtt" in data and isinstance(data["remote_mqtt"], dict):
            rm = data["remote_mqtt"]
            config.remote_mqtt = RemoteMqttConfig(
                enabled=bool(rm.get("enabled", config.remote_mqtt.enabled)),
                host=rm.get("host", config.remote_mqtt.host),
                port=int(rm.get("port", config.remote_mqtt.port)),
                client_id=rm.get("client_id", config.remote_mqtt.client_id),
                keepalive=int(rm.get("keepalive", config.remote_mqtt.keepalive)),
                username=rm.get("username", config.remote_mqtt.username),
                password=rm.get("password", config.remote_mqtt.password),
                use_tls=bool(rm.get("use_tls", config.remote_mqtt.use_tls)),
                ca_cert=rm.get("ca_cert", config.remote_mqtt.ca_cert),
                client_cert=rm.get("client_cert", config.remote_mqtt.client_cert),
                client_key=rm.get("client_key", config.remote_mqtt.client_key),
            )

        if "storage" in data and isinstance(data["storage"], dict):
            st = data["storage"]
            config.storage = StorageConfig(
                db_path=st.get("db_path", config.storage.db_path),
                max_storage_mb=int(st.get("max_storage_mb", config.storage.max_storage_mb)),
                batch_size=int(st.get("batch_size", config.storage.batch_size)),
                flush_interval_sec=float(st.get("flush_interval_sec", config.storage.flush_interval_sec)),
                drain_interval_sec=float(st.get("drain_interval_sec", config.storage.drain_interval_sec)),
            )

        if "device" in data and isinstance(data["device"], dict):
            dev = data["device"]
            config.device = DeviceConfig(
                fleet_id=dev.get("fleet_id", config.device.fleet_id),
                vehicle_id=dev.get("vehicle_id", config.device.vehicle_id),
                imei=dev.get("imei", config.device.imei),
            )

        if "optimization" in data and isinstance(data["optimization"], dict):
            opt = data["optimization"]
            config.optimization = OptimizationConfig(
                enabled=bool(opt.get("enabled", config.optimization.enabled)),
                health_interval_sec=int(opt.get("health_interval_sec", config.optimization.health_interval_sec)),
                publish_health=bool(opt.get("publish_health", config.optimization.publish_health)),
            )

        # Ortam Değişkenleri ile Ezme (Environment Variable Overrides)
        cls._apply_env_overrides(config)
        return config

    @classmethod
    def _apply_env_overrides(cls, config: AgentConfig) -> None:
        if os.getenv("LXC_OPTIMIZATION_ENABLED"):
            config.optimization.enabled = os.environ["LXC_OPTIMIZATION_ENABLED"].lower() in ("true", "1", "yes")
        if os.getenv("LXC_HEALTH_INTERVAL_SEC"):
            config.optimization.health_interval_sec = int(os.environ["LXC_HEALTH_INTERVAL_SEC"])
        if os.getenv("LXC_PUBLISH_HEALTH"):
            config.optimization.publish_health = os.environ["LXC_PUBLISH_HEALTH"].lower() in ("true", "1", "yes")

        if os.getenv("LXC_LOG_LEVEL"):
            config.log_level = os.environ["LXC_LOG_LEVEL"].upper()

        if os.getenv("LXC_WEB_ENABLED"):
            config.web.enabled = os.environ["LXC_WEB_ENABLED"].lower() in ("true", "1", "yes")
        if os.getenv("LXC_WEB_PORT"):
            config.web.port = int(os.environ["LXC_WEB_PORT"])
        if os.getenv("LXC_WEB_AUTH_ENABLED"):
            config.web.auth_enabled = os.environ["LXC_WEB_AUTH_ENABLED"].lower() in ("true", "1", "yes")
        if os.getenv("LXC_WEB_USERNAME"):
            config.web.username = os.environ["LXC_WEB_USERNAME"]
        if os.getenv("LXC_WEB_PASSWORD"):
            config.web.password = os.environ["LXC_WEB_PASSWORD"]

        if os.getenv("LXC_LOCAL_BROKER_HOST"):
            config.local_mqtt.host = os.environ["LXC_LOCAL_BROKER_HOST"]
        if os.getenv("LXC_LOCAL_BROKER_PORT"):
            config.local_mqtt.port = int(os.environ["LXC_LOCAL_BROKER_PORT"])

        if os.getenv("LXC_REMOTE_ENABLED"):
            config.remote_mqtt.enabled = os.environ["LXC_REMOTE_ENABLED"].lower() in ("true", "1", "yes")
        if os.getenv("LXC_REMOTE_BROKER_HOST"):
            config.remote_mqtt.host = os.environ["LXC_REMOTE_BROKER_HOST"]
        if os.getenv("LXC_REMOTE_BROKER_PORT"):
            config.remote_mqtt.port = int(os.environ["LXC_REMOTE_BROKER_PORT"])

        if os.getenv("LXC_STORAGE_DB_PATH"):
            config.storage.db_path = os.environ["LXC_STORAGE_DB_PATH"]
        if os.getenv("LXC_MAX_STORAGE_MB"):
            config.storage.max_storage_mb = int(os.environ["LXC_MAX_STORAGE_MB"])

        if os.getenv("LXC_VEHICLE_ID"):
            config.device.vehicle_id = os.environ["LXC_VEHICLE_ID"]
        if os.getenv("LXC_FLEET_ID"):
            config.device.fleet_id = os.environ["LXC_FLEET_ID"]
        if os.getenv("LXC_IMEI"):
            config.device.imei = os.environ["LXC_IMEI"]

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> AgentConfig:
        """Yapılandırma dosyasını yükler, yoksa varsayılanları döner."""
        if config_path and Path(config_path).is_file():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("Yapılandırma yüklendi: %s", config_path)
                    cfg = cls.from_dict(data)
                    cfg.config_path = str(Path(config_path).resolve())
                    return cfg
            except Exception as e:
                logger.error("Yapılandırma dosyası okunamadı (%s): %s. Varsayılanlar yükleniyor.", config_path, e)

        # Varsayılan konfigürasyon ve ortam değişkenleri
        config = cls()
        if config_path:
            config.config_path = str(Path(config_path).resolve())
        cls._apply_env_overrides(config)
        return config

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("config_path", None)
        return data

    def save(self, path: Optional[str] = None) -> bool:
        """Yapılandırmayı JSON dosyasına atomik olarak kaydeder."""
        target_path = path or self.config_path
        if not target_path:
            logger.warning("Kaydetmek için yapılandırma dosya yolu belirtilmedi.")
            return False

        try:
            target = Path(target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.to_dict()

            tmp_target = target.with_suffix(".tmp")
            with open(tmp_target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp_target.replace(target)
            self.config_path = str(target.resolve())
            logger.info("Yapılandırma başarıyla kaydedildi: %s", target_path)
            return True
        except Exception as e:
            logger.error("Yapılandırma kaydedilemedi (%s): %s", target_path, e)
            return False
