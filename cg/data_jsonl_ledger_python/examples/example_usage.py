"""Append a few records, read them back, then drop one by field match."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.jsonl_ledger import append, forget, read  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "events.jsonl")
        append(path, {"item": "alpha", "note": "first"})
        second = append(path, {"item": "beta", "note": "second"}, max_records=2)
        print(f"after append: {second}")
        loaded = read(path)
        print(f"read: {loaded}")
        assert [row["item"] for row in loaded["records"]] == ["alpha", "beta"]
        dropped = forget(path, match={"item": "alpha"})
        print(f"forget: {dropped}")
        left = read(path)
        assert left["records"] == [{"item": "beta", "note": "second"}]
        assert left["skipped"] == 0


if __name__ == "__main__":
    main()
