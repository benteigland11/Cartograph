"""Validation venvs see a parent venv's packages, and skip installing what they can already import.

system_site_packages only reaches the base interpreter. When cartograph itself runs from a project venv, the
throwaway validation venv gets a .pth pointing at that venv's site-packages, and a declared dependency that already
imports is not reinstalled (so validation also works offline when the deps are present)."""
import os
import sys

from cartograph.languages.python import PythonEngine


def _fake_venv(tmp_path):
    target = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    target.mkdir(parents=True)
    return tmp_path / ".venv", target


def test_a_venv_inside_a_venv_sees_the_parents_packages(tmp_path, monkeypatch):
    venv_dir, target = _fake_venv(tmp_path)
    parent = tmp_path / "project-venv" / "site-packages"
    parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "project-venv"))
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr("site.getsitepackages", lambda: [str(parent), str(tmp_path / "missing")])
    PythonEngine._inherit_parent_site_packages(str(venv_dir))
    assert (target / "_cartograph_parent.pth").read_text().splitlines() == [str(parent)]


def test_outside_a_venv_nothing_is_added(tmp_path, monkeypatch):
    venv_dir, target = _fake_venv(tmp_path)
    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    PythonEngine._inherit_parent_site_packages(str(venv_dir))
    assert not (target / "_cartograph_parent.pth").exists()


def test_importable_reads_the_venvs_own_python():
    engine = PythonEngine()
    assert engine._importable(sys.executable, "pytest>=7")
    assert engine._importable(sys.executable, "pytest-cov") == bool(__import__("importlib").util.find_spec("pytest_cov"))
    assert not engine._importable(sys.executable, "definitely-not-a-real-package-xyz==1.0")


def test_importable_honors_the_declared_version():
    import pytest as _pytest
    engine = PythonEngine()
    have = _pytest.__version__
    assert engine._importable(sys.executable, f"pytest=={have}")
    assert not engine._importable(sys.executable, "pytest==0.0.1")
    assert not engine._importable(sys.executable, "pytest<1")
    assert not engine._importable(sys.executable, "pytest>=7; python_version<'3'")


def test_version_satisfies_subset():
    from cartograph.languages.python import _version_satisfies as ok
    assert ok("2.0", "==2.0.0")
    assert ok("1.4.2", ">=1.2,<2")
    assert not ok("2.0.1", ">=1.2,<2")
    assert ok("1.4.9", "~=1.4.2")
    assert not ok("1.5.0", "~=1.4.2")
    assert ok("1.9", "~=1.4")
    assert not ok("2.0", "~=1.4")
    assert not ok("3.0", "!=3")
    assert not ok("1.0", "~=1")
    # Outside the subset: refuse, so pip installs.
    assert not ok("2.0rc1", ">=1")
    assert not ok("2.1.0+cpu", ">=2")
    assert not ok("2.0", "==2.*")
