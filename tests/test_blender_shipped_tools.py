"""An image that ships Blender's test tools is used as is: a department's fresh validator has no network, and the
PyPI fetch failed with 403 (two Blender widgets dropped from department pull requests, 2026-10-14)."""

from cartograph.languages.blender import BlenderEngine


def _engine(monkeypatch, python="3.13.13"):
    engine = BlenderEngine()
    monkeypatch.setattr(engine, "_interpreter_info", lambda: {"python": python, "pip": False})
    return engine


def test_shipped_tools_are_used_without_pip(monkeypatch, tmp_path):
    for module in ("pytest", "pytest_cov"):
        (tmp_path / "py3.13" / module).mkdir(parents=True)
    monkeypatch.setenv("CARTOGRAPH_BLENDER_TEST_TOOLS", str(tmp_path))
    engine = _engine(monkeypatch)
    engine.install_deps(str(tmp_path), [])
    assert engine._tools_dir == str(tmp_path / "py3.13")


def test_shipped_root_without_this_python_falls_back(monkeypatch, tmp_path):
    (tmp_path / "py3.11" / "pytest").mkdir(parents=True)
    monkeypatch.setenv("CARTOGRAPH_BLENDER_TEST_TOOLS", str(tmp_path))
    monkeypatch.setattr(BlenderEngine, "_tools_root", staticmethod(lambda: str(tmp_path / "data")))
    engine = _engine(monkeypatch)
    try:
        engine.install_deps(str(tmp_path), [])
    except RuntimeError as error:
        assert "has no pip" in str(error)
    else:
        raise AssertionError("expected the fallback to ask for pip")
