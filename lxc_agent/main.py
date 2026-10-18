"""
lxc_agent - Servis Giriş Noktası (Main Application Entry Point)
NetModule NB800 Alpine Linux LXC konteynerinde telemetri servisini başlatır.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Any

from .config import AgentConfig
from .engine import TelemetryEngine


def setup_logging(log_level: str) -> None:
    """Log biçimlendirmesini ve seviyesini yapılandırır."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NetModule NB800 LXC Alpine Telemetri ve Entegrasyon Servisi"
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default="/etc/lxc_agent/config.json",
        help="Yapılandırma dosyası yolu (Varsayılan: /etc/lxc_agent/config.json)",
    )
    parser.add_argument(
        "--local-host",
        dest="local_host",
        help="Yerel Mosquitto broker IP (Varsayılan: 192.168.100.1)",
    )
    parser.add_argument(
        "--local-port",
        dest="local_port",
        type=int,
        help="Yerel Mosquitto broker port (Varsayılan: 1883)",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Loglama seviyesi",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Yapılandırmayı yükle
    config = AgentConfig.load(args.config_path)

    # CLI argümanları ile ezme
    if args.local_host:
        config.local_mqtt.host = args.local_host
    if args.local_port:
        config.local_mqtt.port = args.local_port
    if args.log_level:
        config.log_level = args.log_level

    setup_logging(config.log_level)
    logger = logging.getLogger("lxc_agent")
    logger.info("==================================================")
    logger.info("NB800 lxc_agent Servisi Başlatılıyor...")
    logger.info("Yerel Broker: %s:%d", config.local_mqtt.host, config.local_mqtt.port)
    logger.info("Araç Kimliği: %s | Filo: %s", config.device.vehicle_id, config.device.fleet_id)
    logger.info("Store & Forward Depo: %s (Max: %d MB)", config.storage.db_path, config.storage.max_storage_mb)
    logger.info("==================================================")

    engine = TelemetryEngine(config=config)

    # Sinyal Yönetimi (Graceful Shutdown)
    def shutdown_handler(signum: int, frame: Any) -> None:
        signame = signal.Signals(signum).name
        logger.info("%s sinyali yakalandı, servis güvenle kapatılıyor...", signame)
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        engine.start()
        # Ana iş parçacığını canlı tut
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Kullanıcı müdahalesi (Ctrl+C). Kapatılıyor...")
        engine.stop()
    except Exception as e:
        logger.critical("Beklenmeyen çalışma zamanı hatası: %s", e, exc_info=True)
        engine.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
