import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from batch_chunker import batch_chunker


def test_chunks_by_max_items():
    items = [1, 2, 3, 4, 5]
    batches = list(batch_chunker(items, max_items=2))
    assert batches == [[1, 2], [3, 4], [5]]


def test_chunks_by_max_bytes_using_default_size():
    items = ["aa", "bbb", "c", "dd"]
    batches = list(batch_chunker(items, max_items=10, max_bytes=4))
    assert batches == [["aa"], ["bbb", "c"], ["dd"]]


def test_applies_count_and_byte_limits_together():
    items = ["a", "bb", "ccc", "d", "ee"]
    batches = list(batch_chunker(items, max_items=2, max_bytes=4))
    assert batches == [["a", "bb"], ["ccc", "d"], ["ee"]]


def test_raises_on_non_positive_max_items():
    with pytest.raises(ValueError, match="max_items"):
        list(batch_chunker([1, 2, 3], max_items=0))


def test_raises_on_non_positive_max_bytes():
    with pytest.raises(ValueError, match="max_bytes"):
        list(batch_chunker([1, 2, 3], max_items=2, max_bytes=0))


def test_raises_when_single_item_exceeds_max_bytes():
    with pytest.raises(ValueError, match="single item exceeds max_bytes"):
        list(batch_chunker(["abcdef"], max_items=2, max_bytes=3))


def test_uses_custom_size_function():
    items = [{"k": 1}, {"k": 2, "x": 3}, {"z": 9}]
    def size_fn(item: dict[str, int]) -> int:
        return len(item)

    batches = list(batch_chunker(items, max_items=10, max_bytes=2, size_fn=size_fn))
    assert batches == [[{"k": 1}], [{"k": 2, "x": 3}], [{"z": 9}]]
