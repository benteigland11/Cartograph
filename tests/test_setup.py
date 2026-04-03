"""Tests for the setup command - auto-detection, write, print, workflows."""
import os

import pytest


# ---------------------------------------------------------------------------
# _detect_agent
# ---------------------------------------------------------------------------

def test_detect_claude_from_dotdir(tmp_path):
    """Detect claude from .claude/ directory."""
    from cartograph.cli import _detect_agent
    os.makedirs(tmp_path / ".claude")
    agent, reason = _detect_agent(str(tmp_path))
    assert agent == "claude"
    assert ".claude/" in reason


def test_detect_claude_from_file(tmp_path):
    """Detect claude from CLAUDE.md file."""
    from cartograph.cli import _detect_agent
    (tmp_path / "CLAUDE.md").write_text("# stuff")
    agent, reason = _detect_agent(str(tmp_path))
    assert agent == "claude"
    assert "CLAUDE.md" in reason


def test_detect_cursor(tmp_path):
    """Detect cursor from .cursor/ directory."""
    from cartograph.cli import _detect_agent
    os.makedirs(tmp_path / ".cursor")
    agent, reason = _detect_agent(str(tmp_path))
    assert agent == "cursor"
    assert ".cursor/" in reason


def test_detect_codex(tmp_path):
    """Detect codex from AGENTS.md file."""
    from cartograph.cli import _detect_agent
    (tmp_path / "AGENTS.md").write_text("# agents")
    agent, reason = _detect_agent(str(tmp_path))
    assert agent == "codex"


def test_detect_gemini(tmp_path):
    """Detect gemini from GEMINI.md file."""
    from cartograph.cli import _detect_agent
    (tmp_path / "GEMINI.md").write_text("# gemini")
    agent, reason = _detect_agent(str(tmp_path))
    assert agent == "gemini"


def test_detect_nothing(tmp_path):
    """No agent files returns None."""
    from cartograph.cli import _detect_agent
    agent, reason = _detect_agent(str(tmp_path))
    assert agent is None
    assert reason is None


def test_detect_priority_claude_over_cursor(tmp_path):
    """Claude should win over cursor when both present."""
    from cartograph.cli import _detect_agent
    os.makedirs(tmp_path / ".claude")
    os.makedirs(tmp_path / ".cursor")
    agent, _ = _detect_agent(str(tmp_path))
    assert agent == "claude"


# ---------------------------------------------------------------------------
# cmd_setup - integration via subprocess
# ---------------------------------------------------------------------------

def test_setup_print_mode(tmp_path):
    """--print should output instructions without writing any file."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup", "--print"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "## Cartograph" in result.stdout
    # Should NOT have created a file
    assert not (tmp_path / "CLAUDE.md").exists()


def test_setup_writes_to_detected_agent(tmp_path):
    """Bare setup should auto-detect and write."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "Appended to" in result.stdout
    assert "Detected claude" in result.stdout
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "## Cartograph" in content


def test_setup_appends_not_replaces(tmp_path):
    """Setup should append to existing file, not overwrite."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    existing = "# My Project\n\nSome existing content.\n"
    (tmp_path / "CLAUDE.md").write_text(existing)
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.startswith("# My Project")
    assert "## Cartograph" in content


def test_setup_duplicate_detection(tmp_path):
    """Running setup twice should succeed with 'already exists' message."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    # First run
    subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    # Second run
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "already exists" in result.stdout


def test_setup_custom_file(tmp_path):
    """--file should write to a custom filename."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup", "--file", "opencode.md"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert (tmp_path / "opencode.md").exists()
    content = (tmp_path / "opencode.md").read_text()
    assert "## Cartograph" in content


def test_setup_explicit_agent(tmp_path):
    """--agent should override auto-detection."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup", "--agent", "codex"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert (tmp_path / "AGENTS.md").exists()


def test_setup_no_agent_no_file_shows_help(tmp_path):
    """No agent detected and no flags should show helpful guidance."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    assert "Could not auto-detect" in result.stdout
    assert "--agent" in result.stdout
    assert "--file" in result.stdout


def test_setup_with_workflow(tmp_path):
    """--workflow should include the workflow section."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup", "--workflow"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "### Workflow" in content


def test_setup_without_workflow_shows_tip(tmp_path):
    """Without --workflow, output should hint about it."""
    import subprocess
    os.makedirs(tmp_path / ".claude")
    result = subprocess.run(
        ["python", "-m", "cartograph", "setup"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert "Tip: add --workflow" in result.stdout
