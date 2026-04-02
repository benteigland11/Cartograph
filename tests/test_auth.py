"""Tests for auth module - credential safety."""
import json
import os
import stat

import pytest


def test_save_credentials_rejects_empty_token(tmp_path, monkeypatch):
    """save_credentials should refuse to save an empty token."""
    monkeypatch.setattr("cartograph.auth._CREDENTIALS_FILE",
                        str(tmp_path / "creds.json"))
    from cartograph.auth import save_credentials
    with pytest.raises(ValueError, match="empty id_token"):
        save_credentials("", "refresh", "key")


def test_save_credentials_rejects_whitespace_token(tmp_path, monkeypatch):
    """save_credentials should refuse to save a whitespace-only token."""
    monkeypatch.setattr("cartograph.auth._CREDENTIALS_FILE",
                        str(tmp_path / "creds.json"))
    from cartograph.auth import save_credentials
    with pytest.raises(ValueError, match="empty id_token"):
        save_credentials("   ", "refresh", "key")


def test_save_credentials_writes_file(tmp_path, monkeypatch):
    """Valid credentials should be written to disk."""
    creds_file = str(tmp_path / "creds.json")
    monkeypatch.setattr("cartograph.auth._CREDENTIALS_FILE", creds_file)
    from cartograph.auth import save_credentials
    save_credentials("token123", "refresh456", "key789")
    assert os.path.exists(creds_file)
    with open(creds_file) as f:
        data = json.load(f)
    assert data["id_token"] == "token123"
    assert data["refresh_token"] == "refresh456"


def test_write_credentials_removes_file_on_chmod_failure(tmp_path, monkeypatch):
    """If chmod fails, the credentials file should be deleted."""
    creds_file = str(tmp_path / "creds.json")
    monkeypatch.setattr("cartograph.auth._CREDENTIALS_FILE", creds_file)

    def _bad_chmod(path, mode):
        raise OSError("filesystem does not support permissions")
    monkeypatch.setattr("os.chmod", _bad_chmod)

    from cartograph.auth import save_credentials
    with pytest.raises(OSError, match="Could not set permissions"):
        save_credentials("token", "refresh", "key")
    assert not os.path.exists(creds_file)
