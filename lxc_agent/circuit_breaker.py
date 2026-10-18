"""
lxc_agent - Devre Kesici (Circuit Breaker) ve Üstel Geri Çekilme (Exponential Backoff)
Uzak sunucu/broker çöktüğünde veya yanıt vermediğinde (timeout) sistemi korur,
bağlantı fırtınalarını (reconnect storm) engeller ve sıfır gecikmeyle yerel depoya yönlendirir.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("lxc_agent.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal: Sunucu sağlıklı, istekler iletiliyor.
    OPEN = "OPEN"            # Arızalı: Sunucu erişilemez, istekler doğrudan engelleniyor.
    HALF_OPEN = "HALF_OPEN"  # Test: İyileşme süresi doldu, deneme isteğine izin veriliyor.


class CircuitBreaker:
    """
    Üç durumlu (CLOSED, OPEN, HALF_OPEN) ve üstel geri çekilmeli devre kesici.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        initial_backoff_sec: float = 5.0,
        max_backoff_sec: float = 120.0,
        backoff_factor: float = 2.0,
        jitter_factor: float = 0.2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.initial_backoff_sec = initial_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.backoff_factor = backoff_factor
        self.jitter_factor = jitter_factor

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._current_backoff_sec = initial_backoff_sec
        self._opened_at: Optional[float] = None
        self._next_attempt_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state()
            return self._state

    def _evaluate_state(self) -> None:
        """Süre dolduysa OPEN -> HALF_OPEN geçişini değerlendirir."""
        if self._state == CircuitState.OPEN:
            now = time.monotonic()
            if now >= self._next_attempt_at:
                logger.info(
                    "CircuitBreaker: Geri çekilme süresi doldu (%.1f sn). Test aşamasına geçiliyor (HALF_OPEN).",
                    self._current_backoff_sec,
                )
                self._state = CircuitState.HALF_OPEN

    def can_attempt(self) -> bool:
        """
        Uzak sunucuya yeni bir istek/yayın denemesi yapılıp yapılamayacağını döner.
        OPEN durumunda anında False döner (Sıfır gecikmeli çevrimdışı yönlendirme).
        """
        with self._lock:
            self._evaluate_state()
            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.HALF_OPEN:
                return True
            else:  # CircuitState.OPEN
                return False

    def record_success(self) -> None:
        """Başarılı bir iletimde (ACK alındığında) devreyi kapatır ve sayaçları sıfırlar."""
        with self._lock:
            if self._state != CircuitState.CLOSED or self._failure_count > 0:
                logger.info("CircuitBreaker: Sunucu erişimi başarılı! Devre kapatıldı (CLOSED).")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._current_backoff_sec = self.initial_backoff_sec
            self._opened_at = None
            self._next_attempt_at = 0.0

    def record_failure(self, reason: str = "") -> None:
        """
        Zaman aşımı (timeout), soket hatası veya bağlantı reddinde çağrılır.
        Hata sayısı eşiği geçerse devreyi açar (OPEN).
        """
        with self._lock:
            self._failure_count += 1
            now = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Test isteği başarısız oldu, bekleme süresini katlayarak devreyi tekrar aç
                self._current_backoff_sec = min(
                    self.max_backoff_sec, self._current_backoff_sec * self.backoff_factor
                )
                jitter = self._current_backoff_sec * random.uniform(
                    -self.jitter_factor, self.jitter_factor
                )
                actual_delay = max(0.01, self._current_backoff_sec + jitter)

                self._state = CircuitState.OPEN
                self._opened_at = now
                self._next_attempt_at = now + actual_delay
                logger.warning(
                    "CircuitBreaker: Test isteği başarısız (%s). Devre tekrar AÇILDI (OPEN). Sonraki deneme: %.1f sn sonra.",
                    reason or "Bilinmeyen hata",
                    actual_delay,
                )

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    # Eşik aşıldı, devreyi aç
                    self._state = CircuitState.OPEN
                    self._opened_at = now
                    jitter = self._current_backoff_sec * random.uniform(
                        -self.jitter_factor, self.jitter_factor
                    )
                    actual_delay = max(0.01, self._current_backoff_sec + jitter)
                    self._next_attempt_at = now + actual_delay

                    logger.error(
                        "CircuitBreaker: Üst üste %d hata alındı (%s)! Sunucu erişilemez ilan edildi. "
                        "Devre AÇILDI (OPEN). Tüm telemetri Store-and-Forward'a yönlendiriliyor. "
                        "Sonraki test: %.1f sn sonra.",
                        self._failure_count,
                        reason or "Sunucu yanıt vermiyor",
                        actual_delay,
                    )
                else:
                    logger.warning(
                        "CircuitBreaker: Sunucu isteği başarısız (%d/%d): %s",
                        self._failure_count,
                        self.failure_threshold,
                        reason or "Zaman aşımı",
                    )
