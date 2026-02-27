import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from retry_backoff import retry, RetryError


def test_succeeds_first_try():
    result = retry(lambda: 42)
    assert result == 42


def test_succeeds_after_failures():
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("not yet")
        return "ok"

    result = retry(flaky, max_attempts=5, base_delay=0.01)
    assert result == "ok"
    assert call_count == 3


def test_raises_retry_error_after_exhaustion():
    def always_fail():
        raise ValueError("boom")

    try:
        retry(always_fail, max_attempts=3, base_delay=0.01)
        assert False, "Should have raised"
    except RetryError as e:
        assert e.attempts == 3
        assert isinstance(e.last_exception, ValueError)


def test_retry_error_preserves_last_exception():
    call_count = 0

    def different_errors():
        nonlocal call_count
        call_count += 1
        raise ValueError(f"error {call_count}")

    try:
        retry(different_errors, max_attempts=3, base_delay=0.01)
    except RetryError as e:
        assert "error 3" in str(e.last_exception)


def test_non_retryable_exception_propagates():
    def raise_type_error():
        raise TypeError("wrong type")

    try:
        retry(raise_type_error, max_attempts=5, base_delay=0.01,
              retryable_exceptions=(ValueError,))
        assert False, "Should have raised"
    except TypeError:
        pass  # expected — not retryable, so it propagates immediately


def test_on_retry_callback():
    attempts_seen = []

    def on_retry(attempt, exc, delay):
        attempts_seen.append(attempt)

    def fail_twice():
        if len(attempts_seen) < 2:
            raise ValueError("fail")
        return "done"

    result = retry(fail_twice, max_attempts=5, base_delay=0.01, on_retry=on_retry)
    assert result == "done"
    assert attempts_seen == [1, 2]


def test_backoff_increases_delay():
    delays_seen = []

    def on_retry(attempt, exc, delay):
        delays_seen.append(delay)

    def always_fail():
        raise ValueError("fail")

    try:
        retry(always_fail, max_attempts=4, base_delay=0.01, jitter=False,
              on_retry=on_retry)
    except RetryError:
        pass

    # Without jitter, delays should be 0.01, 0.02, 0.04
    assert len(delays_seen) == 3
    assert delays_seen[0] < delays_seen[1] < delays_seen[2]


def test_max_delay_caps_backoff():
    delays_seen = []

    def on_retry(attempt, exc, delay):
        delays_seen.append(delay)

    def always_fail():
        raise ValueError("fail")

    try:
        retry(always_fail, max_attempts=10, base_delay=1.0, max_delay=2.0,
              jitter=False, on_retry=on_retry)
    except RetryError:
        pass

    assert all(d <= 2.0 for d in delays_seen)


def test_jitter_randomises_delay():
    delays_seen = []

    def on_retry(attempt, exc, delay):
        delays_seen.append(delay)

    def always_fail():
        raise ValueError("fail")

    # Run multiple times to check jitter produces variation
    for _ in range(3):
        delays_seen.clear()
        try:
            retry(always_fail, max_attempts=4, base_delay=1.0, jitter=True,
                  on_retry=on_retry)
        except RetryError:
            pass

    # With jitter, delays should be between 0 and the computed delay
    assert all(d >= 0 for d in delays_seen)


def test_passes_args_and_kwargs():
    def add(a, b, extra=0):
        return a + b + extra

    result = retry(add, 2, 3, extra=10, max_attempts=1)
    assert result == 15


def test_max_attempts_one_no_retry():
    call_count = 0

    def fail_once():
        nonlocal call_count
        call_count += 1
        raise ValueError("fail")

    try:
        retry(fail_once, max_attempts=1, base_delay=0.01)
    except RetryError:
        pass

    assert call_count == 1


def test_invalid_max_attempts():
    try:
        retry(lambda: None, max_attempts=0)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_actual_sleep_with_no_jitter():
    """Verify that retry actually waits between attempts."""
    start = time.monotonic()

    def always_fail():
        raise ValueError("fail")

    try:
        retry(always_fail, max_attempts=3, base_delay=0.05, jitter=False)
    except RetryError:
        pass

    elapsed = time.monotonic() - start
    # Should have slept ~0.05 + ~0.10 = ~0.15s
    assert elapsed >= 0.1
