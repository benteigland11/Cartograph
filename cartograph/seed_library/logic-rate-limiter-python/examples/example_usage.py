"""
Example usage of Token Bucket Rate Limiter.

This file must run cleanly with no external dependencies or network calls.
Uses fake/hardcoded data to demonstrate the widget's logic.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.rate_limiter import RateLimiter, RateLimitExceeded

# Basic usage: 5 requests per second, burst of 3
limiter = RateLimiter(rate=5, capacity=3)

for i in range(5):
    try:
        limiter.acquire()
        print(f"Request {i + 1}: allowed")
    except RateLimitExceeded as e:
        print(f"Request {i + 1}: rejected (retry after {e.retry_after:.2f}s)")

# As a decorator
limiter2 = RateLimiter(rate=100, capacity=5)


@limiter2
def fetch_data(item_id: int) -> dict:
    return {"id": item_id, "value": item_id * 10}


for i in range(5):
    result = fetch_data(i)
    print(f"Fetched: {result}")

# Check available tokens
print(f"Tokens remaining: {limiter2.peek():.1f}")
