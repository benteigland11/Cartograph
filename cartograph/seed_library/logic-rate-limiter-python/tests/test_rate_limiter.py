import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.rate_limiter import RateLimiter, RateLimitExceeded


def test_basic_acquire():
    rl = RateLimiter(rate=10, capacity=10)
    assert rl.acquire() is True


def test_burst_up_to_capacity():
    rl = RateLimiter(rate=1, capacity=5)
    for _ in range(5):
        assert rl.acquire() is True

    # 6th should fail
    try:
        rl.acquire()
        assert False, "Should have raised"
    except RateLimitExceeded:
        pass


def test_rate_limit_exceeded_has_retry_after():
    rl = RateLimiter(rate=1, capacity=1)
    rl.acquire()

    try:
        rl.acquire()
        assert False, "Should have raised"
    except RateLimitExceeded as e:
        assert e.retry_after > 0


def test_tokens_refill_over_time():
    rl = RateLimiter(rate=100, capacity=1)
    rl.acquire()  # drain

    time.sleep(0.05)  # wait for refill (100/s = 5 tokens in 0.05s)
    assert rl.acquire() is True


def test_peek_does_not_consume():
    rl = RateLimiter(rate=10, capacity=5)
    before = rl.peek()
    _ = rl.peek()
    after = rl.peek()
    # peek shouldn't reduce tokens (may increase slightly due to refill)
    assert after >= before - 0.1  # small tolerance for timing


def test_acquire_multiple_tokens():
    rl = RateLimiter(rate=10, capacity=10)
    assert rl.acquire(tokens=5) is True
    assert rl.acquire(tokens=5) is True

    try:
        rl.acquire(tokens=1)
        assert False, "Should have raised"
    except RateLimitExceeded:
        pass


def test_acquire_more_than_capacity_raises():
    rl = RateLimiter(rate=10, capacity=5)
    try:
        rl.acquire(tokens=10)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_blocking_acquire():
    rl = RateLimiter(rate=100, capacity=1)
    rl.acquire()  # drain

    start = time.monotonic()
    assert rl.acquire(block=True) is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.5  # should be fast at 100/s


def test_decorator_usage():
    rl = RateLimiter(rate=100, capacity=5)
    call_count = 0

    @rl
    def my_func():
        nonlocal call_count
        call_count += 1
        return "ok"

    for _ in range(5):
        assert my_func() == "ok"
    assert call_count == 5


def test_thread_safety():
    rl = RateLimiter(rate=1000, capacity=100)
    results = []

    def worker():
        for _ in range(10):
            try:
                rl.acquire()
                results.append(True)
            except RateLimitExceeded:
                results.append(False)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 100
    # At least some should succeed (we have capacity 100)
    assert sum(results) > 0


def test_invalid_rate():
    try:
        RateLimiter(rate=0, capacity=10)
        assert False, "Should have raised"
    except ValueError:
        pass

    try:
        RateLimiter(rate=-1, capacity=10)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_invalid_capacity():
    try:
        RateLimiter(rate=10, capacity=0)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_capacity_refill_does_not_exceed_max():
    rl = RateLimiter(rate=1000, capacity=5)
    time.sleep(0.1)  # way more than enough to refill
    tokens = rl.peek()
    assert tokens <= 5.0
