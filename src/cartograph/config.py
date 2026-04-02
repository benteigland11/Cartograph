"""
Cartograph configuration.

Reads global config from <data_dir>/config.toml. Falls back to defaults
if the file is missing or malformed.

Example config.toml:

    [publish]
    auto_publish = true
    visibility = "public"
    governance = "open"
"""

import os

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

_DEFAULTS = {
    "library": {
        "show_unavailable": True,
        "cloud": True,
    },
    "publish": {
        "auto_publish": False,
        "visibility": "public",
        "governance": "protected",
    },
}

# Flat CLI key -> (section, toml_key, type, choices, description)
_SCHEMA = {
    "auto-publish": ("publish", "auto_publish", "bool", None,
                     "Auto-publish to cloud on every checkin"),
    "visibility":   ("publish", "visibility", "str", ["public", "private"],
                     "Default visibility for published widgets"),
    "governance":   ("publish", "governance", "str", ["open", "protected"],
                     "Default contribution governance model"),
    "cloud":            ("library", "cloud", "bool", None,
                         "Enable cloud registry integration"),
    "show-unavailable": ("library", "show_unavailable", "bool", None,
                         "Show widgets for languages not installed on this machine"),
}


def cloud_enabled() -> bool:
    """Check if cloud registry integration is enabled."""
    return load_config().get("library", {}).get("cloud", True)


def _config_path() -> str:
    """Return path to global config.toml."""
    from .engine import _user_data_dir
    return os.path.join(_user_data_dir(), "config.toml")


def load_config() -> dict:
    """Load global config.toml, merging with defaults."""
    config = {section: dict(values) for section, values in _DEFAULTS.items()}

    path = _config_path()
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


def get_value(key: str):
    """Get a config value by flat key (e.g. 'auto-publish')."""
    if key not in _SCHEMA:
        return None, f"Unknown setting: '{key}'. Run 'cartograph config list' to see available settings."
    section, toml_key, _, _, _ = _SCHEMA[key]
    config = load_config()
    return config.get(section, {}).get(toml_key), None


def set_value(key: str, raw_value: str):
    """Set a config value by flat key. Writes config.toml."""
    if key not in _SCHEMA:
        return f"Unknown setting: '{key}'. Run 'cartograph config list' to see available settings."
    section, toml_key, typ, choices, _ = _SCHEMA[key]

    if typ == "bool":
        if raw_value.lower() in ("true", "1", "yes"):
            value = True
        elif raw_value.lower() in ("false", "0", "no"):
            value = False
        else:
            return f"Invalid boolean: '{raw_value}'. Use true or false."
    else:
        value = raw_value

    if choices and value not in choices:
        return f"Invalid value: '{value}'. Choose from: {', '.join(choices)}"

    config = load_config()
    if section not in config:
        config[section] = {}
    config[section][toml_key] = value

    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_toml(path, config)
    return None


def list_values() -> list[dict]:
    """Return all config keys with current values and defaults."""
    config = load_config()
    result = []
    for key in sorted(_SCHEMA):
        section, toml_key, typ, choices, description = _SCHEMA[key]
        current = config.get(section, {}).get(toml_key)
        default = _DEFAULTS.get(section, {}).get(toml_key)
        result.append({
            "key": key,
            "value": current,
            "default": default,
            "type": typ,
            "choices": choices,
            "description": description,
        })
    return result


def _write_toml(path: str, config: dict):
    """Write config dict as TOML (minimal writer - no dependency needed)."""
    lines = []
    for section, values in sorted(config.items()):
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for k, v in sorted(values.items()):
            if v is None:
                continue
            elif isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
