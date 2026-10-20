"""Mathlib support in the Lean engine: shared pinned workspace, the
mathlib-only dependency gate, transient lakefile/toolchain wiring, and the
setup glue. No Lean toolchain required - everything runs against fake
runners and temp dirs.
"""

import json
import os

import pytest

from cartograph import mathlib_setup
from cartograph.languages.lean import LeanEngine, _MATHLIB_REQUIRE_MARK

PIN = mathlib_setup.MATHLIB_PIN
TOOLCHAIN = mathlib_setup.MATHLIB_TOOLCHAIN


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    import cartograph.engine as engine_mod
    monkeypatch.setattr(engine_mod, "_user_data_dir",
                        lambda: str(tmp_path / "data"))
    monkeypatch.delenv("CARTOGRAPH_HEAVY_DEPS_ROOT", raising=False)
    monkeypatch.delenv("CARTOGRAPH_MATHLIB_ROOT", raising=False)
    return tmp_path / "data"


@pytest.fixture
def engine():
    return LeanEngine()


def make_widget(tmp_path, deps):
    root = tmp_path / "widget"
    root.mkdir()
    (root / "widget.json").write_text(json.dumps({
        "meta": {"id": "formal-example-item-lean"},
        "tech_stack": {"language": "lean", "dependencies": deps},
    }), encoding="utf-8")
    (root / "lakefile.toml").write_text(
        'name = "example_item"\ndefaultTargets = ["example_item"]\n\n'
        '[[lean_lib]]\nname = "example_item"\nsrcDir = "src"\n',
        encoding="utf-8")
    return root


def provision_ready(data_dir):
    mathlib_setup.setup_mathlib(runner=lambda a, c: 0)


# ---- setup glue ------------------------------------------------------------

def test_status_missing_before_setup(data_dir):
    assert mathlib_setup.mathlib_status().state == "missing"


def test_setup_provisions_and_is_idempotent(data_dir):
    calls = []

    def runner(args, cwd):
        calls.append(list(args))
        return 0

    result = mathlib_setup.setup_mathlib(runner=runner)
    assert result.status.ready
    assert calls  # steps actually ran
    n = len(calls)
    again = mathlib_setup.setup_mathlib(runner=runner)
    assert again.status.ready
    assert len(calls) == n  # already ready: no steps re-run


def test_setup_failure_reports_corrupt(data_dir):
    result = mathlib_setup.setup_mathlib(runner=lambda a, c: 2)
    assert not result.status.ready
    assert result.returncode == 2
    assert mathlib_setup.mathlib_status().state == "corrupt"


def test_package_dir_is_inside_workspace(data_dir):
    pkg = mathlib_setup.mathlib_package_dir()
    assert str(mathlib_setup.mathlib_root()) in pkg
    assert pkg.endswith(os.path.join(".lake", "packages", "mathlib"))


# ---- dependency gate -------------------------------------------------------

def test_install_deps_empty_ok(engine, data_dir, tmp_path):
    engine.install_deps(str(make_widget(tmp_path, [])), [])


def test_install_deps_rejects_non_mathlib(engine, data_dir, tmp_path):
    root = make_widget(tmp_path, ["batteries"])
    with pytest.raises(RuntimeError, match="batteries"):
        engine.install_deps(str(root), ["batteries"])


def test_install_deps_mathlib_requires_workspace(engine, data_dir, tmp_path):
    root = make_widget(tmp_path, ["mathlib"])
    with pytest.raises(RuntimeError, match="setup-mathlib"):
        engine.install_deps(str(root), ["mathlib"])


def test_install_deps_mathlib_ok_when_ready(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, [{"name": "mathlib"}])
    engine.install_deps(str(root), [{"name": "mathlib"}])


# ---- lakefile / toolchain wiring -------------------------------------------

def test_sync_injects_require_and_toolchain(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    assert engine._sync_mathlib_require(str(root)) is None
    lakefile = (root / "lakefile.toml").read_text(encoding="utf-8")
    assert _MATHLIB_REQUIRE_MARK in lakefile
    assert 'name = "mathlib"' in lakefile
    assert mathlib_setup.mathlib_package_dir().replace("\\", "/") in lakefile
    assert (root / "lean-toolchain").read_text(
        encoding="utf-8").strip() == TOOLCHAIN


def test_sync_is_idempotent(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    engine._sync_mathlib_require(str(root))
    once = (root / "lakefile.toml").read_text(encoding="utf-8")
    engine._sync_mathlib_require(str(root))
    assert (root / "lakefile.toml").read_text(encoding="utf-8") == once


def test_sync_errors_without_workspace(engine, data_dir, tmp_path):
    root = make_widget(tmp_path, ["mathlib"])
    error = engine._sync_mathlib_require(str(root))
    assert error is not None and "setup-mathlib" in error


def test_sync_noop_for_plain_widget(engine, data_dir, tmp_path):
    root = make_widget(tmp_path, [])
    assert engine._sync_mathlib_require(str(root)) is None
    lakefile = (root / "lakefile.toml").read_text(encoding="utf-8")
    assert _MATHLIB_REQUIRE_MARK not in lakefile
    assert not (root / "lean-toolchain").exists()


def test_sync_strips_require_when_dep_removed(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    engine._sync_mathlib_require(str(root))
    manifest = json.loads((root / "widget.json").read_text(encoding="utf-8"))
    manifest["tech_stack"]["dependencies"] = []
    (root / "widget.json").write_text(json.dumps(manifest), encoding="utf-8")
    engine._sync_mathlib_require(str(root))
    assert _MATHLIB_REQUIRE_MARK not in (root / "lakefile.toml").read_text(
        encoding="utf-8")


def test_cleanup_strips_transient_wiring(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    engine._sync_mathlib_require(str(root))
    engine.cleanup(str(root))
    lakefile = (root / "lakefile.toml").read_text(encoding="utf-8")
    assert _MATHLIB_REQUIRE_MARK not in lakefile
    assert "path =" not in lakefile
    assert not (root / "lean-toolchain").exists()


def workspace_with_packages(data_dir):
    """Simulate a provisioned workspace with a resolved manifest + packages."""
    provision_ready(data_dir)
    ws = mathlib_setup.mathlib_root() + "/" + PIN
    os.makedirs(os.path.join(ws, ".lake", "packages", "batteries"))
    with open(os.path.join(ws, ".lake", "packages", "batteries",
                           "marker.txt"), "w", encoding="utf-8") as f:
        f.write("seeded\n")
    manifest = {
        "version": "1.2.0", "packagesDir": ".lake/packages",
        "packages": [
            {"url": "https://example.org/batteries", "type": "git",
             "rev": "abc123", "name": "batteries",
             "manifestFile": "lake-manifest.json", "inherited": True,
             "configFile": "lakefile.toml"},
            {"url": "https://example.org/mathlib", "type": "git",
             "rev": "def456", "name": "mathlib",
             "manifestFile": "lake-manifest.json", "inherited": False,
             "configFile": "lakefile.lean"},
        ],
    }
    with open(os.path.join(ws, "lake-manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f)
    return ws


def test_seed_copies_packages_and_writes_manifest(engine, data_dir,
                                                  tmp_path):
    workspace_with_packages(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    assert engine._sync_mathlib_require(str(root)) is None
    assert (root / ".lake" / "packages" / "batteries"
            / "marker.txt").is_file()
    manifest = json.loads((root / "lake-manifest.json").read_text(
        encoding="utf-8"))
    entries = {e["name"]: e for e in manifest["packages"]}
    assert entries["mathlib"]["type"] == "path"
    assert entries["batteries"]["rev"] == "abc123"


def test_seed_skipped_when_manifest_exists(engine, data_dir, tmp_path):
    workspace_with_packages(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    (root / "lake-manifest.json").write_text("{}", encoding="utf-8")
    engine._sync_mathlib_require(str(root))
    assert (root / "lake-manifest.json").read_text(
        encoding="utf-8") == "{}"
    assert not (root / ".lake").exists()


def test_seed_best_effort_without_workspace_manifest(engine, data_dir,
                                                     tmp_path):
    provision_ready(data_dir)  # ready stamp but no resolved manifest
    root = make_widget(tmp_path, ["mathlib"])
    assert engine._sync_mathlib_require(str(root)) is None
    assert not (root / "lake-manifest.json").exists()


def test_cleanup_removes_seeded_manifest(engine, data_dir, tmp_path):
    workspace_with_packages(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    engine._sync_mathlib_require(str(root))
    engine.cleanup(str(root))
    assert not (root / "lake-manifest.json").exists()
    assert not (root / ".lake").exists()


def test_cleanup_preserves_blueprint_requires(engine, data_dir, tmp_path):
    provision_ready(data_dir)
    root = make_widget(tmp_path, ["mathlib"])
    with open(root / "lakefile.toml", "a", encoding="utf-8") as f:
        f.write('\n[[require]]\nname = "other_leaf"\n'
                'path = "cg/formal-other-leaf-lean"\n')
    engine._sync_mathlib_require(str(root))
    engine.cleanup(str(root))
    lakefile = (root / "lakefile.toml").read_text(encoding="utf-8")
    assert "other_leaf" in lakefile
    assert _MATHLIB_REQUIRE_MARK not in lakefile


# ---- pin from the widget ---------------------------------------------------

OTHER = "v4.31.0"
OTHER_TOOLCHAIN = "leanprover/lean4:v4.31.0"


def test_bare_mathlib_takes_default_pin():
    assert mathlib_setup.widget_mathlib_pin(["mathlib"]) == PIN
    assert mathlib_setup.widget_mathlib_pin([{"name": "mathlib"}]) == PIN
    assert mathlib_setup.widget_mathlib_pin([]) is None


def test_widget_pin_string_and_dict_forms():
    assert mathlib_setup.widget_mathlib_pin([f"mathlib=={OTHER}"]) == OTHER
    assert mathlib_setup.widget_mathlib_pin(
        [{"name": "mathlib", "version": OTHER}]) == OTHER


@pytest.mark.parametrize("bad", ["mathlib>=v4.31.0", "mathlib==../x"])
def test_widget_pin_rejects_ranges_and_paths(data_dir, bad):
    with pytest.raises(ValueError):
        mathlib_setup.widget_mathlib_pin([bad])


def test_setup_given_pin_infers_toolchain(data_dir):
    result = mathlib_setup.setup_mathlib(runner=lambda a, c: 0, pin=OTHER)
    assert result.status.ready
    assert mathlib_setup.mathlib_toolchain(OTHER) == OTHER_TOOLCHAIN
    assert not mathlib_setup.mathlib_status(PIN).ready  # pins independent


def test_setup_non_tag_pin_needs_toolchain(data_dir):
    with pytest.raises(ValueError, match="toolchain"):
        mathlib_setup.setup_mathlib(runner=lambda a, c: 0, pin="abc123")
    result = mathlib_setup.setup_mathlib(
        runner=lambda a, c: 0, pin="abc123",
        toolchain="leanprover/lean4:v4.30.0")
    assert result.status.ready


def test_widget_pin_wires_that_workspace_and_its_toolchain(engine, data_dir,
                                                           tmp_path):
    # The toolchain comes from the workspace file, not a constant: write
    # an unusual one to prove it.
    mathlib_setup.setup_mathlib(runner=lambda a, c: 0, pin="custom-rev",
                                toolchain="leanprover/lean4:nightly-x")
    root = make_widget(tmp_path, ["mathlib==custom-rev"])
    assert engine._sync_mathlib_require(str(root)) is None
    lakefile = (root / "lakefile.toml").read_text(encoding="utf-8")
    assert mathlib_setup.mathlib_package_dir("custom-rev").replace(
        "\\", "/") in lakefile
    assert (root / "lean-toolchain").read_text(
        encoding="utf-8").strip() == "leanprover/lean4:nightly-x"
    engine.cleanup(str(root))
    assert not (root / "lean-toolchain").exists()


def test_missing_pin_error_names_pin_and_command(engine, data_dir, tmp_path):
    provision_ready(data_dir)  # default pin ready, OTHER is not
    root = make_widget(tmp_path, [f"mathlib=={OTHER}"])
    with pytest.raises(RuntimeError) as exc:
        engine.install_deps(str(root), [f"mathlib=={OTHER}"])
    assert OTHER in str(exc.value)
    assert f"cartograph setup-mathlib --pin {OTHER}" in str(exc.value)
    error = engine._sync_mathlib_require(str(root))
    assert error is not None and f"--pin {OTHER}" in error


def test_default_pin_error_keeps_plain_command(data_dir):
    msg = mathlib_setup.missing_workspace_error("missing")
    assert "cartograph setup-mathlib\n" in msg and "--pin" not in msg


def test_ready_without_toolchain_file_is_corrupt(data_dir):
    provision_ready(data_dir)
    os.remove(os.path.join(mathlib_setup.mathlib_root(), PIN,
                           "lean-toolchain"))
    assert mathlib_setup.mathlib_status().state == "corrupt"


def test_install_deps_accepts_exact_pin(engine, data_dir, tmp_path):
    mathlib_setup.setup_mathlib(runner=lambda a, c: 0, pin=OTHER)
    root = make_widget(tmp_path, [f"mathlib=={OTHER}"])
    engine.install_deps(str(root), [f"mathlib=={OTHER}"])


def test_dep_pinning_rule(engine):
    assert engine._check_dep_pinning(["mathlib"]) == []
    assert engine._check_dep_pinning([f"mathlib=={OTHER}"]) == []
    errors = engine._check_dep_pinning(["mathlib>=v4.0.0"])
    assert errors and "mathlib==<version>" in errors[0]
