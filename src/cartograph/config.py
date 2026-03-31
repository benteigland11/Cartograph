"""
Project-level configuration for Cartograph.

Reads cartograph.toml from the project root. Falls back to defaults
if the file is missing or malformed.

Example cartograph.toml:

    [publish]
    auto_publish = true
    visibility = "public"
"""

import os

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

_DEFAULTS = {
    "publish": {
        "auto_publish": False,
        "visibility": "public",
    },
}


def load_config(project_root: str | None = None) -> dict:
    """Load cartograph.toml from project_root, merging with defaults."""
    if project_root is None:
        project_root = os.getcwd()

    config = {section: dict(values) for section, values in _DEFAULTS.items()}

    path = os.path.join(project_root, "cartograph.toml")
    if not os.path.isfile(path) or tomllib is None:
        return config

    try:
        with open(path, "rb") as f:
            user = tomllib.load(f)
    except Exception:
        return config

    for section, values in user.items():
        if section in config and isinstance(values, dict):
            config[section].update(values)
        else:
            config[section] = values

    return config
