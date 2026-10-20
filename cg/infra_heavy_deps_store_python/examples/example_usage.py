"""
Example usage of Heavy Deps Store.

Resolves a store root from layered settings (an override, a config value,
a default), then locates and lists versions of a heavy dependency in a
temp directory. No network, nothing provisioned for real.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.heavy_deps_store import installed_versions, resolve_root, version_dir

with tempfile.TemporaryDirectory() as tmp:
    default_root = os.path.join(tmp, "data")
    configured = os.path.join(tmp, "big-disk")

    # No override set, a configured value present: the config layer wins.
    root = resolve_root([("EXAMPLE_STORE_ROOT", None),
                         ("config", configured)], default=default_root)
    print(f"root = {root.path} (from {root.source})")

    # A consumer asks for (name, version); the machine says where it lives.
    target = version_dir(root.path, "example-toolkit", "v1.4.0")
    os.makedirs(target)
    with open(os.path.join(target, "ready.json"), "w",
              encoding="utf-8") as f:
        f.write("{}\n")
    os.makedirs(version_dir(root.path, "example-toolkit", "v1.5.0"))

    print(f"example-toolkit v1.4.0 -> {target}")
    print("present:", installed_versions(root.path, "example-toolkit"))
    print("ready:", installed_versions(root.path, "example-toolkit",
                                       marker="ready.json"))
