"""
HMAC-SHA256 stamp signing for the Cartograph cloud trust model.

When a widget is pushed to the cloud, the local client signs its validation
stamp.  The server stores the signature alongside the stamp; on install the
client can verify the stamp hasn't been tampered with.

The signing key is set via CARTOGRAPH_SIGNING_KEY env var.  In a cloud
deployment the server uses a different (private) key for server-side
verification, but locally any consistent key works for round-trip testing.

All functions use stdlib only (hmac, hashlib, json, os) — no extra deps.
"""

import hashlib
import hmac
import json
import os


_ENV_KEY = "CARTOGRAPH_SIGNING_KEY"
_PLACEHOLDER_KEY = "cartograph-local-dev"  # not secret — just for local testing


def _signing_key() -> bytes:
    # Prefer per-user key from credentials (set during OAuth login)
    try:
        from .auth import get_signing_key
        key = get_signing_key()
        if key:
            return key.encode()
    except Exception:
        pass
    # Fallback to env var (CI, tests, server-side)
    key = os.environ.get(_ENV_KEY, _PLACEHOLDER_KEY)
    return key.encode()


def _canonical(stamp: dict) -> bytes:
    """Deterministic JSON serialisation for signing (sorted keys, no whitespace)."""
    # Exclude any existing 'signature' field so signing is idempotent
    clean = {k: v for k, v in stamp.items() if k != "signature"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":")).encode()


def sign_stamp(stamp: dict) -> str:
    """Return an HMAC-SHA256 hex digest over the stamp's canonical form."""
    return hmac.new(_signing_key(), _canonical(stamp), hashlib.sha256).hexdigest()


def verify_stamp(stamp: dict, signature: str) -> bool:
    """Return True if the signature matches the stamp using the local key."""
    expected = sign_stamp(stamp)
    return hmac.compare_digest(expected, signature)
