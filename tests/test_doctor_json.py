"""`cartograph doctor --json`: every language engine with its readiness and each toolchain binary resolved."""
import json
import os
import subprocess
import sys

from cartograph.cli import doctor_languages


def test_doctor_languages_names_every_engine_with_its_binaries():
    languages = doctor_languages()
    assert 'python' in languages and languages['python']['ready'] is True
    for name, entry in languages.items():
        assert set(entry) == {'ready', 'message', 'engine_version', 'runtime_version', 'binaries'}
        for binary in entry['binaries'].values():
            assert os.path.isabs(binary['path']) and binary['source'] in ('override', 'path')


def test_doctor_json_prints_the_languages():
    out = subprocess.run([sys.executable, '-m', 'cartograph.cli', 'doctor', '--json'], capture_output=True, text=True, timeout=600)
    assert out.returncode == 0 and 'python' in json.loads(out.stdout)['languages']
