"""
Tests for the language engine registry and individual engines.
"""
import pytest
from cartograph.languages import get_engine, supported_languages
from cartograph.languages.base import LanguageEngine


def test_registry_returns_engine_for_python():
    engine = get_engine("python")
    assert engine is not None
    assert isinstance(engine, LanguageEngine)


def test_registry_case_insensitive():
    assert get_engine("Python") is get_engine("python")
    assert get_engine("PYTHON") is get_engine("python")


def test_registry_aliases():
    assert get_engine("js") is get_engine("javascript")
    assert get_engine("ts") is get_engine("typescript")


def test_registry_unknown_returns_none():
    assert get_engine("brainfuck") is None
    assert get_engine("") is None


def test_supported_languages():
    langs = supported_languages()
    assert "python" in langs
    assert "javascript" in langs
    assert "nim" in langs


def test_python_engine_run_tests_pass(tmp_path):
    from cartograph.languages.python import PythonEngine
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
    from cartograph.languages.python import PythonEngine
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
    from cartograph.languages.python import PythonEngine
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


def test_python_runtime_version():
    import sys
    engine = get_engine("python")
    rv = engine.runtime_version()
    assert rv is not None
    assert rv.startswith("python ")
    expected = f"python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert rv == expected


def test_js_runtime_version():
    engine = get_engine("javascript")
    available, _ = engine.check_available()
    if not available:
        pytest.skip("node not installed")
    rv = engine.runtime_version()
    assert rv is not None
    assert rv.startswith("node ")


def test_nim_runtime_version():
    engine = get_engine("nim")
    available, _ = engine.check_available()
    if not available:
        pytest.skip("nim not installed")
    rv = engine.runtime_version()
    assert rv is not None
    assert rv.startswith("nim ")


def test_base_engine_runtime_version_is_none():
    engine = LanguageEngine()
    assert engine.runtime_version() is None
