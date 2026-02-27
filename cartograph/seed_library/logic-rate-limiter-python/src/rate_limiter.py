"""Token bucket rate limiter — in-memory, zero dependencies."""

from __future__ import annotations

import threading
import time
from typing import Any


class RateLimitExceeded(Exception):
    """Raised when a request is rejected by the rate limiter."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after:.2f}s"
        )


class RateLimiter:
    """Token bucket rate limiter.

    Parameters
    ----------
    rate : float
        Tokens added per second.
    capacity : int
        Maximum burst size (bucket capacity).
    """

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")

        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, tokens: int = 1, block: bool = False) -> bool:
        """Try to consume *tokens* from the bucket.

        Parameters
        ----------
        tokens : int
            Number of tokens to consume (default 1).
        block : bool
            If True, sleep until tokens are available instead of returning False.

        Returns
        -------
        True if tokens were consumed.

        Raises
        ------
        RateLimitExceeded
            When *block* is False and not enough tokens are available.
        """
        if tokens > self.capacity:
            raise ValueError(
                f"Requested {tokens} tokens but capacity is {self.capacity}"
            )

        with self._lock:
            self._refill()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            if not block:
                wait_time = (tokens - self._tokens) / self.rate
                raise RateLimitExceeded(retry_after=wait_time)

        # Blocking mode: wait and retry
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                wait_time = (tokens - self._tokens) / self.rate

            time.sleep(wait_time)

    def peek(self) -> float:
        """Return current available tokens without consuming any."""
        with self._lock:
            self._refill()
            return self._tokens

    def __call__(self, fn: Any) -> Any:
        """Use as a decorator to rate-limit function calls."""
        import functools

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.acquire()
            return fn(*args, **kwargs)

        return wrapper
