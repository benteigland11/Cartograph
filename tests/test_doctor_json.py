"""`cartograph doctor --json`: every language engine with its readiness and each toolchain binary resolved."""
import json
import os
import subprocess
import sys
import threading

from cartograph.cli import doctor_languages
from cartograph.languages.python import PythonEngine


class _Hangs(PythonEngine):
    """An engine whose availability probe never answers (a toolchain helper holding the probe's pipes)."""
    validation_version = 7

    def __init__(self, release):
        self._release = release

    def check_available(self):
        self._release.wait(30)
        return True, ""


def test_doctor_languages_reports_each_engine():
    languages = doctor_languages({"python": PythonEngine()})
    entry = languages["python"]
    assert entry["ready"] is True
    assert set(entry) == {"ready", "message", "engine_version", "runtime_version", "binaries"}
    assert entry["runtime_version"].startswith("python ")
    for binary in entry["binaries"].values():
        assert os.path.isabs(binary["path"]) and binary["source"] in ("override", "path")


def test_an_engine_that_does_not_answer_is_reported_not_ready():
    release = threading.Event()
    try:
        languages = doctor_languages({"python": PythonEngine(), "stuck": _Hangs(release)}, timeout=1)
    finally:
        release.set()
    assert languages["python"]["ready"] is True
    stuck = languages["stuck"]
    assert stuck["ready"] is False and "did not answer" in stuck["message"]
    assert stuck["engine_version"] == 7


def test_doctor_json_prints_the_languages():
    out = subprocess.run([sys.executable, "-m", "cartograph.cli", "doctor", "--json"],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0 and "python" in json.loads(out.stdout)["languages"]
