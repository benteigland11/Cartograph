"""
Auth token storage for the Cartograph cloud registry.

Tokens are stored in the platform user-config directory with 0o600 permissions
so only the current user can read them.  Nothing in this module makes network
calls — it only manages the local credential file.

Environment overrides (useful for CI/scripts):
  CARTOGRAPH_TOKEN        — skip file storage entirely
  CARTOGRAPH_REGISTRY_URL — override the default registry endpoint
"""

import json
import logging
import os
import stat

from platformdirs import user_config_dir

log = logging.getLogger("cartograph")

_DEFAULT_REGISTRY_URL = "https://api.cartograph.dev"
_TOKEN_FILE = os.path.join(user_config_dir("cartograph"), "credentials.json")


def get_registry_url() -> str:
    return os.environ.get("CARTOGRAPH_REGISTRY_URL", _DEFAULT_REGISTRY_URL)


def get_token() -> str | None:
    """Return the auth token, or None if not authenticated."""
    env = os.environ.get("CARTOGRAPH_TOKEN")
    if env:
        return env
    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
        return data.get("token") or None
    except Exception:
        return None


def is_authenticated() -> bool:
    return get_token() is not None


def save_token(token: str) -> None:
    """Persist a token to disk with restricted permissions."""
    os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
    with open(_TOKEN_FILE, "w") as f:
        json.dump({"token": token}, f)
    try:
        os.chmod(_TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError as e:
        log.debug("Could not set credentials file permissions: %s", e)


def clear_token() -> None:
    """Remove the stored token."""
    try:
        os.remove(_TOKEN_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.debug("Could not remove credentials file: %s", e)
