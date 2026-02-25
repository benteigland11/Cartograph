"""
Tests for the language engine registry and individual engines.
"""
import pytest
from languages import get_engine, supported_languages
from languages.base import LanguageEngine


def test_registry_returns_engine_for_python():
    engine = get_engine("python")
    assert engine is not None
    assert isinstance(engine, LanguageEngine)


def test_registry_case_insensitive():
    assert get_engine("Python") is get_engine("python")
    assert get_engine("PYTHON") is get_engine("python")


def test_registry_aliases_return_stub():
    # v0.1: aliases resolve to unsupported stubs, not None
    assert get_engine("js") is not None
    assert get_engine("ts") is not None
    assert get_engine("c++") is not None


def test_registry_unknown_returns_none():
    assert get_engine("brainfuck") is None
    assert get_engine("") is None


def test_supported_languages_v01():
    langs = supported_languages()
    assert langs == ["python"]


def test_unsupported_engine_returns_clear_error():
    engine = get_engine("javascript")
    assert engine is not None
    result = engine.run_tests("/tmp")
    assert result["passed"] is False
    assert "v0.1" in result["error"]


def test_python_engine_run_tests_pass(tmp_path):
    from languages.python import PythonEngine
    # Create a minimal passing widget
    src = tmp_path / "src"
    src.mkdir()
    (src / "widget.py").write_text("def hello(): return 'hello'\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_widget.py").write_text(
        "import sys, os\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
        "from widget import hello\n"
        "def test_hello():\n"
        "    assert hello() == 'hello'\n"
    )
    engine = PythonEngine()
    result = engine.run_tests(str(tmp_path))
    assert result["passed"] is True


def test_python_engine_run_tests_fail(tmp_path):
    from languages.python import PythonEngine
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_broken.py").write_text(
        "def test_fail():\n"
        "    assert False, 'intentional failure'\n"
    )
    engine = PythonEngine()
    result = engine.run_tests(str(tmp_path))
    assert result["passed"] is False
    assert "error" in result


def test_python_engine_no_tests(tmp_path):
    from languages.python import PythonEngine
    (tmp_path / "tests").mkdir()
    engine = PythonEngine()
    result = engine.run_tests(str(tmp_path))
    assert result["passed"] is False


def test_engine_has_required_interface():
    """Every registered engine must implement install_deps and run_tests."""
    for lang in supported_languages():
        engine = get_engine(lang)
        assert hasattr(engine, "install_deps"), f"{lang} missing install_deps"
        assert hasattr(engine, "run_tests"), f"{lang} missing run_tests"
        assert callable(engine.install_deps)
        assert callable(engine.run_tests)
