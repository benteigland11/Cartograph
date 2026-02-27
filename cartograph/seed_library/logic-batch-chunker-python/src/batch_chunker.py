from collections.abc import Callable, Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def batch_chunker(
    items: Iterable[T],
    *,
    max_items: int,
    max_bytes: int | None = None,
    size_fn: Callable[[T], int] | None = None,
) -> Iterator[list[T]]:
    """
    Yield batches from ``items`` using count and optional byte-size limits.

    Args:
        items: Source iterable to chunk.
        max_items: Maximum number of items allowed in a batch.
        max_bytes: Optional maximum total bytes allowed in a batch.
        size_fn: Optional function that returns byte size for each item.
            If omitted and ``max_bytes`` is provided, item size defaults to
            UTF-8 byte length of ``str(item)``.

    Raises:
        ValueError: If limits are invalid or a single item exceeds ``max_bytes``.
    """
    if max_items <= 0:
        raise ValueError("max_items must be greater than 0")
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be greater than 0 when provided")

    effective_size_fn = size_fn if size_fn is not None else _default_size
    batch: list[T] = []
    batch_bytes = 0

    for item in items:
        item_bytes = 0
        if max_bytes is not None:
            item_bytes = effective_size_fn(item)
            if item_bytes > max_bytes:
                raise ValueError("single item exceeds max_bytes")

        would_exceed_count = len(batch) >= max_items
        would_exceed_bytes = (
            max_bytes is not None and batch and (batch_bytes + item_bytes > max_bytes)
        )
        if would_exceed_count or would_exceed_bytes:
            yield batch
            batch = []
            batch_bytes = 0

        batch.append(item)
        batch_bytes += item_bytes

    if batch:
        yield batch


def _default_size(value: T) -> int:
    return len(str(value).encode("utf-8"))
