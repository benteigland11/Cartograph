"""The PHP coverage-driver probe: one php start for both drivers, and a slow php is a clear error, not a crash."""
import subprocess

from cartograph.languages.php import PhpEngine


def _engine_with(monkeypatch, stdout="", returncode=0, timeout=False):
    engine = PhpEngine()

    def fake_run(cmd, cwd, timeout=60, env=None):
        if timeout_flag:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    timeout_flag = timeout
    monkeypatch.setattr(engine, "_run", fake_run)
    return engine


def test_both_drivers_reported_from_one_probe(monkeypatch):
    assert _engine_with(monkeypatch, "xdebug pcov")._coverage_drivers(".") == (True, True)
    assert _engine_with(monkeypatch, "pcov")._coverage_drivers(".") == (False, True)
    assert _engine_with(monkeypatch, "")._coverage_drivers(".") == (False, False)


def test_failed_php_means_no_driver(monkeypatch):
    assert _engine_with(monkeypatch, "xdebug", returncode=255)._coverage_drivers(".") == (False, False)


def test_slow_php_fails_tests_with_a_clear_message(monkeypatch, tmp_path):
    engine = _engine_with(monkeypatch, timeout=True)
    assert engine._coverage_drivers(".") is None
    result = engine.run_tests(str(tmp_path))
    assert not result["passed"]
    assert "did not respond" in str(result)
    assert "did not respond" in engine.check_optional()[0][2]
