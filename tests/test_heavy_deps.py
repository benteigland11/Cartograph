"""Heavy-dependency store root: config + env resolution, the default that
keeps existing workspaces in place, and the deprecated
CARTOGRAPH_MATHLIB_ROOT alias. Temp dirs only - nothing provisioned."""

import os

import pytest

from cartograph import heavy_deps, mathlib_setup
from cartograph.config import get_value, list_values, set_value


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    import cartograph.engine as engine_mod
    data = tmp_path / "data"
    monkeypatch.setattr(engine_mod, "_user_data_dir", lambda: str(data))
    monkeypatch.delenv(heavy_deps.HEAVY_DEPS_ROOT_ENV, raising=False)
    monkeypatch.delenv("CARTOGRAPH_MATHLIB_ROOT", raising=False)
    return data


def test_default_is_data_dir_lean_mathlib(data_dir):
    # Back-compat: exactly the pre-existing location.
    root = heavy_deps.heavy_deps_root()
    assert root.path == data_dir and root.source == "data dir"
    assert mathlib_setup.mathlib_root() == str(data_dir / "lean-mathlib")
    assert heavy_deps.heavy_dep_dir("mathlib", "v4.32.0") == str(
        data_dir / "lean-mathlib" / "v4.32.0")


def test_config_key_sets_root(data_dir, tmp_path):
    assert set_value("heavy-deps-root", str(tmp_path / "big")) is None
    assert get_value("heavy-deps-root") == (str(tmp_path / "big"), None)
    root = heavy_deps.heavy_deps_root()
    assert root.path == tmp_path / "big"
    assert root.source == "config heavy-deps-root"
    assert mathlib_setup.mathlib_root() == str(tmp_path / "big"
                                               / "lean-mathlib")


def test_config_key_stores_absolute_path(data_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert set_value("heavy-deps-root", "rel/store") is None
    assert get_value("heavy-deps-root")[0] == str(tmp_path / "rel" / "store")


def test_config_key_cleared_by_empty_value(data_dir, tmp_path):
    set_value("heavy-deps-root", str(tmp_path / "big"))
    assert set_value("heavy-deps-root", "") is None
    assert heavy_deps.heavy_deps_root().source == "data dir"


def test_config_key_listed_with_data_dir_default(data_dir):
    item = next(i for i in list_values() if i["key"] == "heavy-deps-root")
    assert item["default"] == str(data_dir)
    assert item["value"] is None


def test_env_beats_config(data_dir, tmp_path, monkeypatch):
    set_value("heavy-deps-root", str(tmp_path / "cfg"))
    monkeypatch.setenv(heavy_deps.HEAVY_DEPS_ROOT_ENV, str(tmp_path / "env"))
    root = heavy_deps.heavy_deps_root()
    assert root.path == tmp_path / "env"
    assert root.source == heavy_deps.HEAVY_DEPS_ROOT_ENV
    assert mathlib_setup.mathlib_root() == str(tmp_path / "env"
                                               / "lean-mathlib")


def test_blank_env_is_ignored(data_dir, monkeypatch):
    monkeypatch.setenv(heavy_deps.HEAVY_DEPS_ROOT_ENV, "  ")
    assert heavy_deps.heavy_deps_root().source == "data dir"


def test_legacy_mathlib_root_names_the_lean_mathlib_folder(data_dir,
                                                           tmp_path,
                                                           monkeypatch):
    # The deprecated variable points at <root>/lean-mathlib itself, so a
    # bind mount with any name works.
    monkeypatch.setenv("CARTOGRAPH_MATHLIB_ROOT", str(tmp_path / "bound"))
    assert mathlib_setup.mathlib_root() == str(tmp_path / "bound")
    assert heavy_deps.heavy_dep_dir("mathlib", "v4.32.0") == str(
        tmp_path / "bound" / "v4.32.0")
    assert "deprecated" in mathlib_setup.mathlib_root_source()


def test_legacy_alias_beats_config(data_dir, tmp_path, monkeypatch):
    set_value("heavy-deps-root", str(tmp_path / "cfg"))
    monkeypatch.setenv("CARTOGRAPH_MATHLIB_ROOT", str(tmp_path / "bound"))
    assert mathlib_setup.mathlib_root() == str(tmp_path / "bound")


def test_new_env_beats_legacy_alias(data_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("CARTOGRAPH_MATHLIB_ROOT", str(tmp_path / "bound"))
    monkeypatch.setenv(heavy_deps.HEAVY_DEPS_ROOT_ENV, str(tmp_path / "env"))
    assert mathlib_setup.mathlib_root() == str(tmp_path / "env"
                                               / "lean-mathlib")


def test_workspace_provisioned_under_env_root_is_found(data_dir, tmp_path,
                                                       monkeypatch):
    # Provision on the "host" (default root), then look from a "sandbox"
    # whose data dir differs but whose env names the host's root.
    mathlib_setup.setup_mathlib(runner=lambda a, c: 0)
    import cartograph.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_user_data_dir",
                        lambda: str(tmp_path / "sandbox-data"))
    assert not mathlib_setup.mathlib_status().ready
    monkeypatch.setenv(heavy_deps.HEAVY_DEPS_ROOT_ENV, str(data_dir))
    assert mathlib_setup.mathlib_status().ready


def test_requested_version_forms():
    assert heavy_deps.requested_version("mathlib") is None
    assert heavy_deps.requested_version("mathlib==v4.31.0") == "v4.31.0"
    assert heavy_deps.requested_version(" mathlib == v4.31.0 ") == "v4.31.0"
    assert heavy_deps.requested_version(
        {"name": "mathlib", "pin": "v4.30.0"}) == "v4.30.0"
    assert heavy_deps.requested_version({"name": "mathlib"}) is None
    with pytest.raises(ValueError, match="mathlib==<version>"):
        heavy_deps.requested_version("mathlib~=v4.31")


def test_unregistered_dependency_is_refused(data_dir):
    with pytest.raises(KeyError, match="not a registered heavy dependency"):
        heavy_deps.heavy_dep_dir("torch", "2.5.0")


def test_bad_version_segment_refused(data_dir):
    with pytest.raises(ValueError):
        heavy_deps.heavy_dep_dir("mathlib", "../escape")
