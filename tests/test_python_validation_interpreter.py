"""CARTOGRAPH_PYTHON names the interpreter Python widgets are validated with.

Heavy dependencies such as torch may be installed for a different Python than the one Cartograph runs on; upstream's
parent-venv inheritance only reaches a venv of the same interpreter. With CARTOGRAPH_PYTHON set, the validation venv
is made from that interpreter and inherits its package directories, heavy dependencies are looked up there, and the
src import check, sidecar pytest and the runtime version stamped at checkin use it. Unset, nothing changes."""
import os
import subprocess
import sys
import venv

from cartograph.languages.python import PythonEngine


def _venv_python(venv_dir):
    return os.path.join(venv_dir, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_dir, "bin", "python")


def _site_packages(python):
    out = subprocess.run([python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_unset_it_is_the_running_interpreter(monkeypatch):
    monkeypatch.delenv("CARTOGRAPH_PYTHON", raising=False)
    engine = PythonEngine()
    assert engine.validation_python() == sys.executable
    assert engine._venv_python() == sys.executable
    v = sys.version_info
    assert engine.runtime_version() == f"python {v.major}.{v.minor}.{v.micro}"


def test_set_it_names_the_validation_interpreter(monkeypatch, tmp_path):
    other = tmp_path / "other"
    venv.create(str(other), with_pip=False)
    python = _venv_python(str(other))
    monkeypatch.setenv("CARTOGRAPH_PYTHON", python)
    engine = PythonEngine()
    assert engine.validation_python() == python
    assert engine._venv_python() == python
    v = sys.version_info
    assert engine.runtime_version() == f"python {v.major}.{v.minor}.{v.micro}"


def test_the_validation_venv_inherits_the_named_interpreters_packages(monkeypatch, tmp_path):
    other = tmp_path / "other"
    venv.create(str(other), with_pip=False)
    python = _venv_python(str(other))
    monkeypatch.setenv("CARTOGRAPH_PYTHON", python)
    target = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    target.mkdir(parents=True)
    PythonEngine._inherit_parent_site_packages(str(tmp_path / ".venv"))
    inherited = (target / "_cartograph_parent.pth").read_text().splitlines()
    assert os.path.normcase(_site_packages(python)) in {os.path.normcase(p) for p in inherited}


def test_a_heavy_dependency_is_looked_up_in_the_named_interpreter(monkeypatch, tmp_path):
    """The pre-install check asks the interpreter that will run the tests, not the one Cartograph runs on."""
    other = tmp_path / "other"
    venv.create(str(other), with_pip=False)
    python = _venv_python(str(other))
    site = _site_packages(python)
    os.makedirs(os.path.join(site, "torch"))
    open(os.path.join(site, "torch", "__init__.py"), "w").close()
    dist = os.path.join(site, "torch-9.9.9.dist-info")
    os.makedirs(dist)
    with open(os.path.join(dist, "METADATA"), "w") as handle:
        handle.write("Metadata-Version: 2.1\nName: torch\nVersion: 9.9.9\n")
    engine = PythonEngine()
    assert engine._importable(python, "torch")
    assert engine._importable(python, "torch>=9")
    assert not engine._importable(python, "torch<9")
