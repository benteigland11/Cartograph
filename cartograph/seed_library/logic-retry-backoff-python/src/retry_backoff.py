"""Retry with exponential backoff, jitter, and configurable exceptions."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Sequence, Type


class RetryError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, last_exception: Exception, attempts: int) -> None:
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"Failed after {attempts} attempts. Last error: {last_exception}"
        )


def retry(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Sequence[Type[Exception]] = (Exception,),
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Call *fn* with retries using exponential backoff.

    Parameters
    ----------
    fn : callable
        The function to call.
    *args :
        Positional arguments forwarded to *fn*.
    max_attempts : int
        Total number of attempts (including the first call).
    base_delay : float
        Initial delay in seconds before the first retry.
    max_delay : float
        Upper bound on delay between retries.
    backoff_factor : float
        Multiplier applied to the delay after each attempt.
    jitter : bool
        If True, randomise the delay between 0 and the computed delay.
    retryable_exceptions : sequence of exception types
        Only retry on these exceptions. All others propagate immediately.
    on_retry : callable, optional
        Hook called before each retry with (attempt, exception, delay).
    **kwargs :
        Keyword arguments forwarded to *fn*.

    Returns
    -------
    Whatever *fn* returns on a successful call.

    Raises
    ------
    RetryError
        When all attempts are exhausted.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    delay = base_delay
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except tuple(retryable_exceptions) as exc:
            last_exc = exc
            if attempt == max_attempts:
                break

            actual_delay = random.uniform(0, delay) if jitter else delay
            actual_delay = min(actual_delay, max_delay)

            if on_retry is not None:
                on_retry(attempt, exc, actual_delay)

            time.sleep(actual_delay)
            delay = min(delay * backoff_factor, max_delay)

    raise RetryError(last_exc, max_attempts)  # type: ignore[arg-type]
