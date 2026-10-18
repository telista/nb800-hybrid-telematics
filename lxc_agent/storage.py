"""
lxc_agent - Store-and-Forward Depolama Katmanı (Storage Layer)
SQLite WAL (Write-Ahead Logging) tabanlı, ani güç kesintilerine dayanıklı (crash-resilient),
kota sınırlamalı (circular buffer) ve 1970 zaman damgası düzeltme (back-patching) destekli depo.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("lxc_agent.storage")


class StoreAndForwardQueue:
    """
    SQLite WAL modunda çalışan, dairesel kuyruk ve zaman düzeltme yetenekli
    çevrimdışı telemetri depolama yöneticisi.
    """

    def __init__(
        self,
        db_path: str = "/var/lib/lxc_agent/store_and_forward.db",
        max_storage_mb: int = 50,
        flush_interval_sec: float = 3.0,
        max_uncommitted_records: int = 10,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.max_storage_bytes = max(1, max_storage_mb) * 1024 * 1024
        self.flush_interval_sec = flush_interval_sec
        self.max_uncommitted_records = max_uncommitted_records

        self._lock = threading.RLock()
        self._uncommitted_count = 0
        self._last_commit_time = time.monotonic()
        self._closed = False

        # Dizin yoksa oluştur
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = self._init_database()
        logger.info(
            "StoreAndForwardQueue başlatıldı: %s (Max: %d MB, WAL modunda)",
            self.db_path,
            max_storage_mb,
        )

    def _init_database(self) -> sqlite3.Connection:
        """Veritabanı bağlantısını açar, WAL modunu ve tabloları yapılandırır."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None,  # Otomatik transaction yönetimi
        )
        conn.row_factory = sqlite3.Row

        with conn:
            # WAL ve güvenilirlik ayarları (Hard cut koruması)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA busy_timeout = 5000;")

            # Tablo tanımı
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    monotonic_time REAL NOT NULL,
                    time_synced INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_synced ON telemetry_queue(time_synced);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_id ON telemetry_queue(id);"
            )

        return conn

    def get_total_storage_bytes(self) -> int:
        """Ana db, WAL ve SHM dosyalarının toplam boyutunu döner."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(f"{self.db_path}{suffix}")
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def _prune_if_exceeded_quota(self) -> None:
        """
        Dosya boyutu belirlenen üst limiti (max_storage_mb) aştığında
        en eski kayıtları (FIFO) silerek flash dolmasını engeller.
        """
        current_bytes = self.get_total_storage_bytes()
        if current_bytes <= self.max_storage_bytes:
            return

        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM telemetry_queue;")
            total_rows = cursor.fetchone()[0]
            if total_rows <= 2:
                return

            prune_count = max(1, min(50, total_rows // 4))
            logger.warning(
                "Depolama kotası aşıldı (%d KB > %d KB). En eski %d kayıt temizleniyor...",
                current_bytes // 1024,
                self.max_storage_bytes // 1024,
                prune_count,
            )

            with self._conn:
                self._conn.execute(
                    """
                    DELETE FROM telemetry_queue
                    WHERE id IN (
                        SELECT id FROM telemetry_queue ORDER BY id ASC LIMIT ?
                    );
                    """,
                    (prune_count,),
                )
            # WAL dosyasını küçültmek için checkpoint çalıştır
            try:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.Error as e:
                logger.debug("Checkpoint hatası: %s", e)

    def enqueue(
        self,
        topic: str,
        payload: Dict[str, Any] | str,
        timestamp: Optional[int] = None,
        time_synced: bool = True,
    ) -> int:
        """
        Yeni bir telemetri mesajını çevrimdışı kuyruğa ekler.
        Wear-leveling (flash ömrü) için periyodik batch commit uygular.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("StoreAndForwardQueue kapatılmış.")

            now_mono = time.monotonic()
            now_wall = time.time()

            if isinstance(payload, dict):
                payload_str = json.dumps(payload, ensure_ascii=False)
                if timestamp is None and "timestamp" in payload:
                    try:
                        timestamp = int(payload["timestamp"])
                    except (ValueError, TypeError):
                        timestamp = int(now_wall)
            else:
                payload_str = str(payload)

            if timestamp is None:
                timestamp = int(now_wall)

            # 1970 kontrolü: Eğer zaman 2020 öncesiyse time_synced=False kabul edilir.
            # Zaman 2020 sonrasındaysa (> 1577836800), geçerli bir saat senkronu var demektir.
            if timestamp < 1577836800:
                time_synced = False
            elif timestamp >= 1577836800:
                time_synced = True

            cursor = self._conn.execute(
                """
                INSERT INTO telemetry_queue
                (topic, payload, timestamp, monotonic_time, time_synced, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    topic,
                    payload_str,
                    timestamp,
                    now_mono,
                    1 if time_synced else 0,
                    now_wall,
                ),
            )
            row_id = cursor.lastrowid or 0
            self._uncommitted_count += 1

            # Flash koruması: Eşik aşılmadıkça veya süre dolmadıkça her yazmada fsync yapma
            elapsed = now_mono - self._last_commit_time
            if (
                self._uncommitted_count >= self.max_uncommitted_records
                or elapsed >= self.flush_interval_sec
            ):
                self.flush()

            # Dairesel kota kontrolü
            self._prune_if_exceeded_quota()

            return row_id

    def flush(self) -> None:
        """Kuyruktaki bekleyen kayıtları atomik olarak diske commit eder."""
        with self._lock:
            if self._closed:
                return
            try:
                with self._conn:
                    pass  # isolation_level=None olduğundan execute otomatik işlem yürütür
                self._uncommitted_count = 0
                self._last_commit_time = time.monotonic()
            except sqlite3.Error as e:
                logger.error("Veritabanı commit hatası: %s", e)

    def fetch_batch(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Gönderilmek üzere sıradaki en eski 'limit' adet kaydı çeker.
        Dönen liste elemanları: {'id', 'topic', 'payload', 'timestamp', 'time_synced'}
        """
        with self._lock:
            if self._closed:
                return []
            cursor = self._conn.execute(
                """
                SELECT id, topic, payload, timestamp, time_synced
                FROM telemetry_queue
                ORDER BY id ASC
                LIMIT ?;
                """,
                (limit,),
            )
            records = []
            for row in cursor.fetchall():
                try:
                    payload_data = json.loads(row["payload"])
                except Exception:
                    payload_data = row["payload"]
                records.append(
                    {
                        "id": row["id"],
                        "topic": row["topic"],
                        "payload": payload_data,
                        "timestamp": row["timestamp"],
                        "time_synced": bool(row["time_synced"]),
                    }
                )
            return records

    def acknowledge_batch(self, ids: List[int]) -> int:
        """Merkeze başarıyla iletilen kayıtları kuyruktan siler."""
        if not ids:
            return 0
        with self._lock:
            if self._closed:
                return 0
            placeholders = ",".join("?" for _ in ids)
            with self._conn:
                cursor = self._conn.execute(
                    f"DELETE FROM telemetry_queue WHERE id IN ({placeholders});",
                    ids,
                )
                deleted = cursor.rowcount
            return deleted

    def back_patch_timestamps(self, true_sync_timestamp: int) -> int:
        """
        RTC pili bulunmayan cihazın 1970 tarihiyle kaydettiği kayıtları
        'local/event/time -> sync' geldiğinde geriye dönük gerçek zamanla günceller.
        """
        with self._lock:
            if self._closed:
                return 0

            now_mono = time.monotonic()
            cursor = self._conn.execute(
                """
                SELECT id, payload, monotonic_time, timestamp
                FROM telemetry_queue
                WHERE time_synced = 0;
                """
            )
            rows = cursor.fetchall()
            if not rows:
                return 0

            patched_count = 0
            with self._conn:
                for row in rows:
                    rec_id = row["id"]
                    rec_mono = row["monotonic_time"]
                    rec_ts = row["timestamp"]

                    # Eğer kayıt zaten geçerli bir zaman damgasına sahipse (> 2020),
                    # var olan damgayı bozma, yalnızca time_synced=1 olarak işaretle.
                    if rec_ts and rec_ts >= 1577836800:
                        corrected_ts = rec_ts
                        payload_raw = row["payload"]
                        try:
                            p_data = json.loads(payload_raw)
                            if isinstance(p_data, dict):
                                if p_data.get("time_synced") is False:
                                    p_data["time_synced"] = True
                                new_payload_str = json.dumps(p_data, ensure_ascii=False)
                            else:
                                new_payload_str = payload_raw
                        except Exception:
                            new_payload_str = payload_raw
                    else:
                        # 1970 zamanıyla kaydedilmiş eski kayıt
                        elapsed_since_rec = max(0.0, now_mono - rec_mono)
                        corrected_ts = int(true_sync_timestamp - elapsed_since_rec)
                        payload_raw = row["payload"]
                        try:
                            p_data = json.loads(payload_raw)
                            if isinstance(p_data, dict):
                                p_data["timestamp"] = corrected_ts
                                p_data["_time_patched"] = True
                                if "time_synced" in p_data:
                                    p_data["time_synced"] = True
                                new_payload_str = json.dumps(p_data, ensure_ascii=False)
                            else:
                                new_payload_str = payload_raw
                        except Exception:
                            new_payload_str = payload_raw

                    self._conn.execute(
                        """
                        UPDATE telemetry_queue
                        SET timestamp = ?, payload = ?, time_synced = 1
                        WHERE id = ?;
                        """,
                        (corrected_ts, new_payload_str, rec_id),
                    )
                    patched_count += 1

            logger.info(
                "Timestamp Back-Patching tamamlandı: %d kayıt gerçek zaman damgasıyla (%d) güncellendi.",
                patched_count,
                true_sync_timestamp,
            )
            return patched_count

    def count(self) -> int:
        """Kuyrukta bekleyen toplam kayıt sayısını döner."""
        with self._lock:
            if self._closed:
                return 0
            cursor = self._conn.execute("SELECT COUNT(*) FROM telemetry_queue;")
            row = cursor.fetchone()
            return row[0] if row else 0

    def checkpoint(self) -> None:
        """WAL günlüğündeki bekleyen işlemleri ana veritabanı dosyasına aktarır (checkpoint)."""
        with self._lock:
            if self._closed:
                return
            self.flush()
            try:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.Error as e:
                logger.debug("Checkpoint hatası: %s", e)

    def purge(self) -> int:
        """
        Kuyruktaki tüm telemetri kayıtlarını kalıcı olarak siler ve
        WAL günlüğünü TRUNCATE ederek dosya alanını sıfırlar.
        Silinen toplam kayıt sayısını döner.
        """
        with self._lock:
            if self._closed:
                return 0
            with self._conn:
                cursor = self._conn.execute("DELETE FROM telemetry_queue;")
                deleted_count = cursor.rowcount
            self._uncommitted_count = 0
            self._last_commit_time = time.monotonic()
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.execute("VACUUM;")
            except sqlite3.Error as e:
                logger.debug("Purge sonrası WAL checkpoint/vacuum hatası: %s", e)

            logger.info("StoreAndForwardQueue temizlendi (Purge): %d kayıt silindi.", deleted_count)
            return deleted_count

    def close(self) -> None:
        """Veritabanını güvenle kapatır ve bekleyen veriyi flush eder."""
        with self._lock:
            if self._closed:
                return
            self.flush()
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
            self._conn.close()
            self._closed = True
            logger.info("StoreAndForwardQueue kapatıldı.")
