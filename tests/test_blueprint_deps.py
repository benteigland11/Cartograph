"""Tests for `cartograph blueprint add-dep` / `remove-dep`."""

import json
import os

import pytest

from cartograph.engine import Cartograph


def _write_installed_widget(project_dir, widget_id, version="1.0.0"):
    """Drop an installed widget under <project>/cg/<py_dir>/."""
    py_dir = widget_id.replace("-", "_")
    wdir = os.path.join(project_dir, "cg", py_dir)
    os.makedirs(os.path.join(wdir, "src"))
    domain = widget_id.split("-")[0]
    name = widget_id[len(domain) + 1: -len("-python") - 1]
    manifest = {
        "meta": {
            "id": widget_id, "name": name, "version": version,
            "domain": domain, "tags": ["a", "b", "c"],
        },
        "tech_stack": {"language": "python", "dependencies": []},
        "description": "fake widget",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    open(os.path.join(wdir, "src", "__init__.py"), "w").close()
    return wdir


def _write_blueprint(project_dir, name="auth-flow", deps=None, version="0.1.0"):
    deps = deps or []
    bp_id = f"bp-{name}-python"
    py_dir = bp_id.replace("-", "_")
    bp = os.path.join(project_dir, "cg", py_dir)
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))
    manifest = {
        "id": bp_id,
        "name": name,
        "language": "python",
        "version": version,
        "description": "real description",
        "tags": ["auth", "demo", "test"],
        "dependencies": deps,
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return bp


@pytest.fixture
def carto(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    return Cartograph(library_path=str(lib))


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


# --- add-dep -----------------------------------------------------------------

def test_add_dep_pins_to_installed_version(carto, project):
    _write_installed_widget(str(project), "backend-greet-python", version="1.2.3")
    bp = _write_blueprint(str(project))
    res = carto.blueprint_add_dep(blueprint_path=bp, widget_id="backend-greet-python",
                                  validate=False)
    assert res["status"] == "success", res
    assert res["added"] == {"id": "backend-greet-python", "version": "1.2.3"}
    with open(os.path.join(bp, "blueprint.json")) as f:
        stored = json.load(f)
    assert stored["dependencies"] == [{"id": "backend-greet-python", "version": "1.2.3"}]


def test_add_dep_rejects_when_widget_not_installed(carto, project):
    bp = _write_blueprint(str(project))
    res = carto.blueprint_add_dep(blueprint_path=bp, widget_id="backend-missing-python",
                                  validate=False)
    assert res["status"] == "error"
    assert "not installed" in res["message"].lower()


def test_add_dep_rejects_blueprint_dep(carto, project):
    bp = _write_blueprint(str(project))
    res = carto.blueprint_add_dep(blueprint_path=bp, widget_id="bp-other-python",
                                  validate=False)
    assert res["status"] == "error"
    assert "leaf-only" in res["message"]


def test_add_dep_rejects_cross_language(carto, project):
    _write_installed_widget(str(project), "backend-greet-python")
    bp = _write_blueprint(str(project))
    res = carto.blueprint_add_dep(blueprint_path=bp, widget_id="backend-x-nim",
                                  validate=False)
    assert res["status"] == "error"
    assert "single language" in res["message"]


def test_add_dep_rejects_self_reference(carto, project):
    bp = _write_blueprint(str(project))
    res = carto.blueprint_add_dep(blueprint_path=bp, widget_id="bp-auth-flow-python",
                                  validate=False)
    assert res["status"] == "error"
    # The leaf-only guard fires first for any bp- id; that's fine — the
    # net behavior is "self-reference is rejected".
    assert "blueprint" in res["message"].lower() or "itself" in res["message"].lower()


def test_add_dep_idempotency_blocks_duplicate(carto, project):
    _write_installed_widget(str(project), "backend-greet-python", version="1.0.0")
    bp = _write_blueprint(str(project))
    first = carto.blueprint_add_dep(blueprint_path=bp, widget_id="backend-greet-python",
                                    validate=False)
    assert first["status"] == "success", first
    second = carto.blueprint_add_dep(blueprint_path=bp, widget_id="backend-greet-python",
                                     validate=False)
    assert second["status"] == "error"
    assert "already a dep" in second["message"]


def test_add_dep_requires_blueprint_under_cg(carto, tmp_path):
    """A blueprint copied somewhere outside cg/ must be rejected."""
    stray = tmp_path / "stray"
    stray.mkdir()
    bp = _write_blueprint(str(stray))  # ends up at tmp/stray/cg/bp_auth_flow_python — that's still cg/
    # Move the bp dir to a location whose parent isn't cg/.
    import shutil
    detached = tmp_path / "detached"
    shutil.copytree(bp, str(detached))
    res = carto.blueprint_add_dep(blueprint_path=str(detached),
                                  widget_id="backend-greet-python", validate=False)
    assert res["status"] == "error"
    assert "cg/" in res["message"]


def test_add_dep_rejects_missing_blueprint_json(carto, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    res = carto.blueprint_add_dep(blueprint_path=str(bare),
                                  widget_id="backend-greet-python", validate=False)
    assert res["status"] == "error"
    assert "blueprint.json" in res["message"]


def test_add_dep_rejects_path_not_found(carto, tmp_path):
    res = carto.blueprint_add_dep(blueprint_path=str(tmp_path / "nope"),
                                  widget_id="backend-greet-python", validate=False)
    assert res["status"] == "error"
    assert "not found" in res["message"].lower()


# --- remove-dep --------------------------------------------------------------

def test_remove_dep_drops_entry(carto, project):
    _write_installed_widget(str(project), "backend-greet-python")
    bp = _write_blueprint(str(project), deps=[
        {"id": "backend-greet-python", "version": "1.0.0"},
    ])
    res = carto.blueprint_remove_dep(blueprint_path=bp,
                                     widget_id="backend-greet-python",
                                     validate=False)
    assert res["status"] == "success", res
    assert res["removed"] == {"id": "backend-greet-python", "version": "1.0.0"}
    with open(os.path.join(bp, "blueprint.json")) as f:
        stored = json.load(f)
    assert stored["dependencies"] == []


def test_remove_dep_rejects_missing(carto, project):
    bp = _write_blueprint(str(project))
    res = carto.blueprint_remove_dep(blueprint_path=bp,
                                     widget_id="backend-greet-python",
                                     validate=False)
    assert res["status"] == "error"
    assert "not a dep" in res["message"]


# --- validation rollback (slow: real venv) -----------------------------------

@pytest.mark.slow
def test_add_dep_reverts_manifest_when_validation_fails(carto, project, tmp_path):
    """If post-edit validation fails, the manifest is restored to its prior state."""
    # Install a widget that the blueprint won't actually use — adding it as a
    # dep is fine schema-wise, but the blueprint's example doesn't import it,
    # so installation+test runs still pass. To force a validation failure,
    # we install a widget with a *broken* dep_sources path: pin to a version
    # that doesn't exist locally so _resolve_dep_sources can't find it.
    _write_installed_widget(str(project), "backend-greet-python", version="9.9.9")
    bp = _write_blueprint(str(project))
    # Author the blueprint with src/ that imports nothing from cg/ so example
    # runs cleanly *before* the edit (validate would still fail because deps
    # is empty — schema requires non-empty deps).
    # Instead, trigger failure post-edit: pin to a version not in the lib.
    # Library has nothing, so validator's _resolve_dep_sources will fail on
    # the just-added dep.
    bp_manifest_before = json.load(open(os.path.join(bp, "blueprint.json")))
    res = carto.blueprint_add_dep(blueprint_path=bp,
                                  widget_id="backend-greet-python",
                                  validate=True)
    assert res["status"] != "success"
    assert res.get("reverted") is True
    # Manifest restored.
    bp_manifest_after = json.load(open(os.path.join(bp, "blueprint.json")))
    assert bp_manifest_after == bp_manifest_before
