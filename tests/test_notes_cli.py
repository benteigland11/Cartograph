"""`cartograph notes`: the canonical library notes from Cartograph's rules (what validate and checkin restore)."""
import json
import subprocess
import sys


def _notes(*args, cwd=None):
    out = subprocess.run([sys.executable, "-m", "cartograph.cli", "notes", *args],
                         capture_output=True, text=True, timeout=120, cwd=cwd)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_notes_for_a_language_and_domain():
    result = _notes("--language", "python", "--domain", "backend")
    assert "pytest" in result["library_notes"]["language"]
    assert result["library_notes"]["domain"]


def test_notes_for_a_working_copy_are_the_canonical_text(tmp_path):
    (tmp_path / "widget.json").write_text(json.dumps({
        "meta": {"id": "w", "domain": "universal"},
        "tech_stack": {"language": "python", "dependencies": []},
        "library_notes": {"general": "AGENT-EDIT", "language": "AGENT-EDIT"},
    }))
    result = _notes(str(tmp_path))
    assert result["language"] == "python" and result["domain"] == "universal"
    assert result["library_notes"]["general"].startswith("Single responsibility")
    assert "AGENT-EDIT" not in json.dumps(result["library_notes"])
