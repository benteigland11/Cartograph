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
