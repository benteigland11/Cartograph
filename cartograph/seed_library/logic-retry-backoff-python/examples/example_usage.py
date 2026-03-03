"""
Example usage of Retry with Backoff.

This file must run cleanly with no external dependencies or network calls.
Uses fake/hardcoded data to demonstrate the widget's logic.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.retry_backoff import retry, RetryError

# Simulate a flaky function that fails twice then succeeds
call_count = 0


def flaky_api_call(endpoint: str) -> dict:
    global call_count
    call_count += 1
    if call_count < 3:
        raise ConnectionError(f"Timeout reaching {endpoint}")
    return {"status": "ok", "data": [1, 2, 3]}


# Basic retry — succeeds on 3rd attempt
result = retry(flaky_api_call, "/api/data", max_attempts=5, base_delay=0.01)
print(f"Got result after {call_count} attempts: {result}")

# With a callback to log retries
def log_retry(attempt, exc, delay):
    print(f"  Attempt {attempt} failed: {exc} — retrying in {delay:.3f}s")

call_count = 0
result = retry(
    flaky_api_call, "/api/data",
    max_attempts=5,
    base_delay=0.01,
    on_retry=log_retry,
)
print(f"Got result: {result}")

# Handling exhaustion
def always_fails():
    raise ValueError("Service down")

try:
    retry(always_fails, max_attempts=3, base_delay=0.01)
except RetryError as e:
    print(f"Gave up: {e}")
