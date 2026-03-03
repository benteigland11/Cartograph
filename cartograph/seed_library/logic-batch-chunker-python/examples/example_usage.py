"""
Example usage of Logic Batch Chunker.

This file must run and exit cleanly with no user input, no network calls,
and no external dependencies. Use fake/hardcoded data to demonstrate the API.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.batch_chunker import batch_chunker

records = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
]

print("Count-based chunking:")
for batch in batch_chunker(records, max_items=2):
    print(batch)

print("\nByte-aware chunking:")
for batch in batch_chunker(records, max_items=5, max_bytes=10):
    print(batch)
