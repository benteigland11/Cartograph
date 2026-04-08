"""
Tests for the contamination and validation pipeline.

This is the most critical gate in widget quality. Every check that can block
or warn during checkin must be tested here.

Structure:
  1. Base capability tests - parameterized across all engines. These verify
     the 8 required contamination checks defined in base.py. If a language
     can't pass these, it doesn't ship.

  2. Language-specific tests - checks unique to each engine's validate_widget
     (print detection, echo detection, console.log, etc.).

  3. Shared validation tests - dep pinning, orchestrator delegation, base
     class regex fallback.
"""
import json
import os
import shutil
from unittest.mock import patch

import pytest

from cartograph.languages.python import PythonEngine
from cartograph.languages.javascript import JavaScriptEngine
from cartograph.languages.nim import NimEngine
from cartograph.languages.systemverilog import SystemVerilogEngine
from cartograph.languages.base import LanguageEngine
from cartograph.contamination import scan_contamination


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _make_widget(tmp_path, language, src_filename, src_code,
                 test_code="", dependencies=None):
    """Create a minimal widget dir with the given source and return its path."""
    wdir = str(tmp_path)
    manifest = {
        "meta": {"id": "test-widget", "name": "Test Widget",
                 "version": "1.0.0", "tags": ["test"], "domain": "backend"},
        "description": "Test widget for contamination checks.",
        "tech_stack": {
            "language": language,
            "dependencies": dependencies or [],
        },
    }
    _write(os.path.join(wdir, "widget.json"), json.dumps(manifest, indent=2))
    _write(os.path.join(wdir, "src", src_filename), src_code)
    if language == "python":
        _write(os.path.join(wdir, "src", "__init__.py"), "")
    if test_code:
        test_name = "test_" + src_filename
        _write(os.path.join(wdir, "tests", test_name), test_code)
    return wdir


# ---------------------------------------------------------------------------
# Per-language scan helpers
# ---------------------------------------------------------------------------

def _scan(tmp_path, language, ext, src_code, test_code="", dependencies=None):
    """Run scan_contamination for a given language engine."""
    engines = {
        "python": PythonEngine,
        "javascript": JavaScriptEngine,
        "nim": NimEngine,
        "systemverilog": SystemVerilogEngine,
    }
    wdir = _make_widget(tmp_path, language, f"module.{ext}", src_code,
                        test_code, dependencies)
    engine = engines[language]()
    tech_stack = {"language": language, "dependencies": dependencies or []}
    return engine.scan_contamination(wdir, tech_stack)


# ---------------------------------------------------------------------------
# Test data: per-language source snippets for each contamination check
#
# Each entry: (src_code, test_code_or_None, dependencies_or_None)
# src_code is planted in src/, test_code in tests/ if provided.
# ---------------------------------------------------------------------------

# Noop source per language (clean code that triggers nothing)
CLEAN = {
    "python":     ("def hello():\n    return 'world'\n", "", None),
    "javascript": ("function hello() { return 'world' }\n", "", None),
    "nim":        ("proc hello*(): string =\n  \"world\"\n", "", None),
    "systemverilog": ("module clean #(parameter int W = 8)(\n"
                      "    input logic clk, input logic rst_n,\n"
                      "    input logic [W-1:0] d_in, output logic [W-1:0] d_out\n"
                      ");\n    always_ff @(posedge clk) begin\n"
                      "        if (!rst_n) d_out <= '0;\n"
                      "        else d_out <= d_in;\n"
                      "    end\nendmodule\n", "", None),
}

# Check 1: Absolute paths in src/ -> block
ABS_PATH_SRC = {
    "python":     'LOG = "/home/user/logs/app.log"\n',
    "javascript": "const LOG = '/home/user/logs/app.log'\n",
    "nim":        'let logDir = "/home/user/logs/app"\n',
    "systemverilog": 'module m; localparam string P = "/home/user/data"; endmodule\n',
}

# Check 2: Credentials in src/ -> block
CREDENTIAL_SRC = {
    "python":     'api_key = "sk-abc123verylongkey"\n',
    "javascript": "const api_key = 'sk-abc123verylongkey'\n",
    "nim":        'let api_key = "sk-abc123verylongkey"\n',
    "systemverilog": 'module m;\nlocalparam string api_key = "sk-abc123verylongkey";\nendmodule\n',
}

# Check 2b: Credentials in tests/ -> warning (not block)
CREDENTIAL_TEST = {
    "python":     'password = "fake_test_password_123"\n',
    "javascript": "const password = 'fake_test_password_123'\n",
    "nim":        'let password = "fake_test_password_123"\n',
    "systemverilog": 'module m;\npassword = "fake_test_password_123";\nendmodule\n',
}

# Check 3: Hardcoded URLs -> block
URL_SRC = {
    "python":     'API = "https://api.mycompany.com/v1"\n',
    "javascript": "const API = 'https://api.mycompany.com/v1'\n",
    "nim":        'let api = "https://api.mycompany.com/v1"\n',
    "systemverilog": 'module m; localparam string U = "https://api.mycompany.com/v1"; endmodule\n',
}

# Check 3b: localhost/example.com URLs -> allowed
URL_ALLOWED = {
    "python":     'API = "http://localhost:8080/api"\n',
    "javascript": "const API = 'http://localhost:8080/api'\n",
    "nim":        'let api = "http://localhost:8080/api"\n',
    "systemverilog": 'module m; localparam string U = "http://localhost:8080/api"; endmodule\n',
}

# Check 4: Hardcoded IPs -> block
IP_SRC = {
    "python":     'HOST = "192.168.1.100"\n',
    "javascript": "const HOST = '192.168.1.100'\n",
    "nim":        'let host = "192.168.1.100"\n',
    "systemverilog": 'module m; localparam string H = "192.168.1.100"; endmodule\n',
}

# Check 5: Sleep in src/ -> block
SLEEP_SRC = {
    "python":     "import time\ntime.sleep(1)\n",
    "javascript": "setTimeout(() => {}, 1000)\n",
    "nim":        "sleep(1000)\n",
}

# Check 5b: Sleep in tests/ with small duration -> no warning
SLEEP_TEST_SMALL = {
    "python":     "import time\ntime.sleep(0.5)\n",
    "javascript": "setTimeout(() => {}, 500)\n",
    "nim":        "sleep(500)\n",
}

# Check 5c: Sleep in tests/ with large duration -> warning
SLEEP_TEST_LARGE = {
    "python":     "import time\ntime.sleep(5)\n",
    "javascript": "setTimeout(() => {}, 5000)\n",
    "nim":        "sleep(5000)\n",
}

# Check 6: Hardcoded values -> warning
HARDCODED_VALUE = {
    "python":     "TIMEOUT = 30\n",
    "javascript": "const TIMEOUT = 30\n",
    "nim":        "let timeout = 30\n",
}

# Check 7: Env var access -> warning
ENV_VAR = {
    "python":     "import os\nv = os.getenv('KEY')\n",
    "javascript": "const v = process.env.KEY\n",
    "nim":        'let v = getEnv("KEY")\n',
}

# Check 8: Unlisted imports -> warning
UNLISTED_IMPORT = {
    "python":     "import requests\n",
    "javascript": "const axios = require('axios')\n",
    "nim":        "import somepkg\n",
}

# Check 8b: Listed imports -> no warning
LISTED_IMPORT = {
    "python":     ("import requests\n", ["requests>=2.0.0"]),
    "javascript": ("const axios = require('axios')\n", ["axios>=1.0.0"]),
    "nim":        ("import somepkg\n", ["somepkg>=1.0.0"]),
}

# Check 8c: Stdlib imports -> no warning
STDLIB_IMPORT = {
    "python":     "import json\n",
    "javascript": "const path = require('path')\n",
    "nim":        "import std/json\n",
}

# File extensions per language
EXT = {"python": "py", "javascript": "js", "nim": "nim", "systemverilog": "sv"}

# Which languages need external tools to run their scanners
NEEDS_TOOL = {"javascript": "node", "nim": "nim", "systemverilog": "iverilog"}


# ---------------------------------------------------------------------------
# 1. BASE CAPABILITY TESTS - parameterized across all languages
# ---------------------------------------------------------------------------

# All languages with contamination engines
LANGUAGES = ["python", "javascript", "nim", "systemverilog"]

# Languages with native sleep/import/env detection (not applicable to SV)
LANGUAGES_SOFTWARE = ["python", "javascript", "nim"]


def _skip_if_missing(lang):
    """Skip test if the language's external tool is not installed."""
    tool = NEEDS_TOOL.get(lang)
    if tool and not shutil.which(tool):
        pytest.skip(f"{tool} not installed")


class TestContaminationStandard:
    """Every language engine must pass all 8 contamination checks.

    These tests are the contract defined in base.py's scan_contamination
    docstring. A new language engine is not ready until it passes all of these.
    """

    # -- Clean code --

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_clean_code_no_findings(self, tmp_path, lang):
        _skip_if_missing(lang)
        src, test, deps = CLEAN[lang]
        result = _scan(tmp_path, lang, EXT[lang], src, test, deps)
        assert result["blocks"] == [], f"{lang}: unexpected blocks: {result['blocks']}"
        assert result["warnings"] == [], f"{lang}: unexpected warnings: {result['warnings']}"

    # -- Check 1: Absolute paths -> block --

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_absolute_path_blocks(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], ABS_PATH_SRC[lang])
        assert any("path" in b.lower() for b in result["blocks"]), \
            f"{lang}: absolute path not blocked: {result}"

    # -- Check 2: Credentials -> block in src, warn in tests --

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_credential_in_src_blocks(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], CREDENTIAL_SRC[lang])
        assert any("credential" in b.lower() for b in result["blocks"]), \
            f"{lang}: credential not blocked: {result}"

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_credential_in_tests_warns_not_blocks(self, tmp_path, lang):
        _skip_if_missing(lang)
        clean_src = CLEAN[lang][0]
        result = _scan(tmp_path, lang, EXT[lang], clean_src,
                        test_code=CREDENTIAL_TEST[lang])
        assert not any("credential" in b.lower() for b in result["blocks"]), \
            f"{lang}: test credential should not block: {result['blocks']}"
        assert any("credential" in w.lower() for w in result["warnings"]), \
            f"{lang}: test credential should warn: {result['warnings']}"

    # -- Check 3: Hardcoded URLs -> block --

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_hardcoded_url_warns(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], URL_SRC[lang])
        assert any("url" in w.lower() for w in result["warnings"]), \
            f"{lang}: hardcoded URL not warned: {result}"

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_localhost_url_allowed(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], URL_ALLOWED[lang])
        assert not any("url" in b.lower() for b in result["blocks"]), \
            f"{lang}: localhost URL should not block: {result['blocks']}"

    # -- Check 4: Hardcoded IPs -> block --

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_hardcoded_ip_blocks(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], IP_SRC[lang])
        assert any("ip" in b.lower() for b in result["blocks"]), \
            f"{lang}: hardcoded IP not blocked: {result}"

    # -- Check 5: Sleep/blocking -> block in src, conditional warn in tests --
    # (Not applicable to SystemVerilog - it has its own timing rules)

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_sleep_in_src_blocks(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], SLEEP_SRC[lang])
        assert any("sleep" in b.lower() for b in result["blocks"]), \
            f"{lang}: sleep not blocked in src: {result}"

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_sleep_in_tests_small_no_warning(self, tmp_path, lang):
        _skip_if_missing(lang)
        clean_src = CLEAN[lang][0]
        result = _scan(tmp_path, lang, EXT[lang], clean_src,
                        test_code=SLEEP_TEST_SMALL[lang])
        assert not any("sleep" in w.lower() for w in result["warnings"]), \
            f"{lang}: small sleep should not warn: {result['warnings']}"

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_sleep_in_tests_large_warns(self, tmp_path, lang):
        _skip_if_missing(lang)
        clean_src = CLEAN[lang][0]
        result = _scan(tmp_path, lang, EXT[lang], clean_src,
                        test_code=SLEEP_TEST_LARGE[lang])
        assert any("sleep" in w.lower() for w in result["warnings"]), \
            f"{lang}: large sleep should warn: {result['warnings']}"

    # -- Check 6: Hardcoded values -> warning --
    # (Not applicable to SystemVerilog - it has its own hardcoded constant rules)

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_hardcoded_value_warns(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], HARDCODED_VALUE[lang])
        assert any("hardcoded" in w.lower() for w in result["warnings"]), \
            f"{lang}: hardcoded value should warn: {result['warnings']}"

    # -- Check 7: Env var access -> warning --
    # (Not applicable to SystemVerilog - no env vars in HDL)

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_env_var_warns(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], ENV_VAR[lang])
        assert any("env" in w.lower() for w in result["warnings"]), \
            f"{lang}: env var should warn: {result['warnings']}"

    # -- Check 8: Unlisted imports -> warning --
    # (Not applicable to SystemVerilog - no package imports in the same sense)

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_unlisted_import_warns(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], UNLISTED_IMPORT[lang])
        assert any("unlisted" in w.lower() or "import" in w.lower()
                    for w in result["warnings"]), \
            f"{lang}: unlisted import should warn: {result['warnings']}"

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_listed_import_no_warning(self, tmp_path, lang):
        _skip_if_missing(lang)
        src, deps = LISTED_IMPORT[lang]
        result = _scan(tmp_path, lang, EXT[lang], src, dependencies=deps)
        assert not any("unlisted" in w.lower() for w in result["warnings"]), \
            f"{lang}: listed import should not warn: {result['warnings']}"

    @pytest.mark.parametrize("lang", LANGUAGES_SOFTWARE)
    def test_stdlib_import_no_warning(self, tmp_path, lang):
        _skip_if_missing(lang)
        result = _scan(tmp_path, lang, EXT[lang], STDLIB_IMPORT[lang])
        assert not any("unlisted" in w.lower() for w in result["warnings"]), \
            f"{lang}: stdlib import should not warn: {result['warnings']}"


# ---------------------------------------------------------------------------
# 2. LANGUAGE-SPECIFIC TESTS - checks unique to each engine
# ---------------------------------------------------------------------------

@pytest.mark.python
class TestPythonSpecific:
    """Python-only validation and contamination checks."""

    # -- validate_widget --

    def test_print_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "python", "mod.py", "print('debug')\n")
        result = PythonEngine().validate_widget(wdir, [])
        assert result["passed"] is False
        assert "print()" in result["error"]

    def test_missing_init_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "python", "mod.py", "def f(): pass\n")
        os.remove(os.path.join(wdir, "src", "__init__.py"))
        result = PythonEngine().validate_widget(wdir, [])
        assert result["passed"] is False
        assert "__init__.py" in result["error"]

    def test_clean_passes(self, tmp_path):
        wdir = _make_widget(tmp_path, "python", "mod.py", "def f(): pass\n")
        result = PythonEngine().validate_widget(wdir, [])
        assert result["passed"] is True

    # -- contamination extras --

    def test_asyncio_sleep_in_src_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        "import asyncio\nasync def f():\n    await asyncio.sleep(1)\n")
        assert any("sleep" in b.lower() for b in result["blocks"])

    def test_from_import_sleep_in_src_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        "from time import sleep\nsleep(5)\n")
        assert any("sleep" in b.lower() for b in result["blocks"])

    def test_from_import_sleep_aliased_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        "from time import sleep as nap\nnap(5)\n")
        assert any("sleep" in b.lower() for b in result["blocks"])

    def test_from_import_sleep_in_tests_large_warns(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        "def f(): pass\n",
                        test_code="from time import sleep\nsleep(5)\n")
        assert any("sleep" in w.lower() for w in result["warnings"])

    def test_absolute_path_windows_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        'LOG = "C:\\\\Users\\\\dev\\\\logs"\n')
        assert any("path" in b.lower() for b in result["blocks"])

    def test_absolute_path_root_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        'CFG = "/root/.config/myapp"\n')
        assert any("path" in b.lower() for b in result["blocks"])

    def test_ip_with_port_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py", 'HOST = "10.0.0.5:8080"\n')
        assert any("IP" in b for b in result["blocks"])

    def test_example_com_url_allowed(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        'API = "https://example.com/test"\n')
        assert not any("URL" in b for b in result["blocks"])

    def test_os_environ_warns(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        "import os\nv = os.environ['KEY']\n")
        assert any("environ" in w for w in result["warnings"])

    def test_hardcoded_string_warns(self, tmp_path):
        result = _scan(tmp_path, "python", "py", 'MODEL = "gpt-4"\n')
        assert any("Hardcoded value" in w for w in result["warnings"])

    def test_password_in_src_blocks(self, tmp_path):
        result = _scan(tmp_path, "python", "py",
                        'password = "supersecretpassword"\n')
        assert any("credential" in b.lower() for b in result["blocks"])


@pytest.mark.javascript
class TestJSSpecific:
    """JavaScript-only validation and contamination checks."""

    @pytest.fixture(autouse=True)
    def _require_node(self):
        if not shutil.which("node"):
            pytest.skip("Node.js not installed")

    # -- validate_widget --

    def test_console_log_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "javascript", "mod.js",
                            "console.log('debug')\n")
        result = JavaScriptEngine().validate_widget(wdir, [])
        assert result["passed"] is False
        assert "console" in result["error"].lower()

    def test_process_exit_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "javascript", "mod.js",
                            "process.exit(1)\n")
        result = JavaScriptEngine().validate_widget(wdir, [])
        assert result["passed"] is False
        assert "process.exit" in result["error"]

    def test_eval_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "javascript", "mod.js",
                            "eval('alert(1)')\n")
        result = JavaScriptEngine().validate_widget(wdir, [])
        assert result["passed"] is False
        assert "eval" in result["error"].lower()

    def test_clean_passes(self, tmp_path):
        wdir = _make_widget(tmp_path, "javascript", "mod.js",
                            "function hello() { return 1 }\n")
        result = JavaScriptEngine().validate_widget(wdir, [])
        assert result["passed"] is True

    # -- contamination extras --

    def test_setinterval_in_src_blocks(self, tmp_path):
        result = _scan(tmp_path, "javascript", "js",
                        "setInterval(() => {}, 1000)\n")
        assert any("sleep" in b.lower() or "setInterval" in b
                    for b in result["blocks"])

    def test_builtin_import_no_warning(self, tmp_path):
        result = _scan(tmp_path, "javascript", "js",
                        "const path = require('path')\n")
        assert not any("unlisted" in w.lower() for w in result["warnings"])

    def test_multiline_require_warns_unlisted(self, tmp_path):
        result = _scan(
            tmp_path, "javascript", "js",
            "const axios = require(\n  'axios'\n)\n"
        )
        assert any("unlisted" in w.lower() for w in result["warnings"])

    def test_multiline_import_warns_unlisted(self, tmp_path):
        result = _scan(
            tmp_path, "javascript", "js",
            "import {\n  thing\n} from 'axios'\n"
        )
        assert any("unlisted" in w.lower() for w in result["warnings"])

    def test_multiline_settimeout_in_src_blocks(self, tmp_path):
        result = _scan(
            tmp_path, "javascript", "js",
            "setTimeout(\n  () => {},\n  1000\n)\n"
        )
        assert any("sleep" in b.lower() for b in result["blocks"])


@pytest.mark.nim
class TestNimSpecific:
    """Nim-only validation and contamination checks."""

    @pytest.fixture(autouse=True)
    def _require_nim(self):
        if not shutil.which("nim"):
            pytest.skip("Nim not installed")

    # -- validate_widget (nim check + compile check + scanner errors) --

    def test_echo_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            'echo "debug"\n')
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is False
        assert "echo" in result["error"].lower()

    def test_quit_in_src_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim", "quit(1)\n")
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is False
        assert "quit" in result["error"].lower()

    def test_when_is_main_module_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            'proc f() = discard\nwhen isMainModule:\n  f()\n')
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is False
        assert "isMainModule" in result["error"] or "main_module" in result["error"].lower()

    def test_clean_passes(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            "proc hello*(): string =\n  \"world\"\n")
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is True

    # -- contamination extras --

    def test_sleep_async_in_src_blocks(self, tmp_path):
        result = _scan(tmp_path, "nim", "nim",
                        "import std/asyncdispatch\nsleepAsync(1000)\n")
        assert any("sleep" in b.lower() for b in result["blocks"])

    def test_global_pragma_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            'var x {.global.} = 0\n')
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is False

    def test_os_specific_when_defined_fails(self, tmp_path):
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            'when defined(windows):\n  discard\n')
        engine = NimEngine()
        result = engine.validate_widget(wdir, [])
        assert result["passed"] is False

    def test_old_style_stdlib_import_warns(self, tmp_path):
        result = _scan(tmp_path, "nim", "nim", "import strutils\n")
        assert any("std/" in w.lower() or "modern nim" in w.lower() or "old-style" in w.lower()
                   for w in result["warnings"])

    def test_top_level_var_warns(self, tmp_path):
        result = _scan(tmp_path, "nim", "nim", "var cache = 0\nproc hello*(): string =\n  \"ok\"\n")
        assert any("top-level mutable state" in w.lower() or "top-level" in w.lower()
                   for w in result["warnings"])

    def test_hardcoded_value_in_test_file_not_warned(self, tmp_path):
        """Test files legitimately have expected values and fixtures -
        hardcoded value warnings should be src/ only."""
        clean_src = "proc hello*(): string =\n  \"ok\"\n"
        test_code = ("import std/unittest\n"
                     "let expected = 42\n"
                     "const FIXTURE = \"abc\"\n"
                     "suite \"x\":\n  test \"y\":\n    check 1 == 1\n")
        result = _scan(tmp_path, "nim", "nim", clean_src, test_code=test_code)
        assert not any("hardcoded" in w.lower() for w in result["warnings"]), \
            f"hardcoded values in test files should not warn: {result['warnings']}"

    def test_hardcoded_url_in_test_file_not_warned(self, tmp_path):
        """Test files often use mock URLs - URL warnings should be src/ only."""
        clean_src = "proc hello*(): string =\n  \"ok\"\n"
        test_code = ('import std/unittest\n'
                     'let url = "https://api.mocksite.com/v1"\n'
                     'suite "x":\n  test "y":\n    check 1 == 1\n')
        result = _scan(tmp_path, "nim", "nim", clean_src, test_code=test_code)
        assert not any("hardcoded url" in w.lower() for w in result["warnings"]), \
            f"hardcoded URLs in test files should not warn: {result['warnings']}"

    def test_local_src_module_import_from_tests_not_warned(self, tmp_path):
        """A test file importing a local widget src/ module is not an unlisted
        external dep — the scanner must allowlist filenames found in src/.
        Regression for the user-reported false positive on test_rotate_frame.nim
        importing rotate_frame_lib (which lives at src/rotate_frame_lib.nim)."""
        # src module name matches what tests/ will import
        src_code = "func rotate*(x: int): int = x + 1\n"
        test_code = ("import std/unittest\n"
                     "import rotate_frame_lib\n"
                     "suite \"r\":\n  test \"t\":\n    check rotate(1) == 2\n")
        # Use _make_widget directly so we control the src filename
        wdir = _make_widget(tmp_path, "nim", "rotate_frame_lib.nim", src_code,
                            test_code=test_code)
        engine = NimEngine()
        result = engine.scan_contamination(wdir, {"language": "nim", "dependencies": []})
        unlisted = [w for w in result["warnings"]
                    if "rotate_frame_lib" in w and "unlisted" in w.lower()]
        assert not unlisted, \
            f"local src/ module should not warn as unlisted: {result['warnings']}"

    def test_top_level_var_in_test_file_not_warned(self, tmp_path):
        """Test files often have top-level helper state."""
        clean_src = "proc hello*(): string =\n  \"ok\"\n"
        test_code = ('import std/unittest\n'
                     'var counter = 0\n'
                     'suite "x":\n  test "y":\n    counter.inc; check counter == 1\n')
        result = _scan(tmp_path, "nim", "nim", clean_src, test_code=test_code)
        assert not any("top-level" in w.lower() for w in result["warnings"]), \
            f"top-level vars in test files should not warn: {result['warnings']}"

    def test_nim_stdlib_list_complete(self):
        """Verify the scanner's nimStdlib covers all modules shipped with nim."""
        import subprocess, re as _re

        # Ask the compiler for its own lib directory (works with choosenim,
        # system installs, and any other layout).
        script = 'import std/os; echo getCurrentCompilerExe().parentDir.parentDir / "lib"'
        res = subprocess.run(
            ["nim", "e", "--hints:off", "-"],
            input=script, capture_output=True, text=True, timeout=15,
        )
        if res.returncode != 0:
            pytest.skip(f"nim e failed: {res.stderr.strip()}")
        lib_root = res.stdout.strip()
        if not os.path.isdir(lib_root):
            pytest.skip(f"Could not find nim lib dir at {lib_root}")

        # Collect all .nim module names from stdlib directories
        stdlib_dirs = [
            "pure", "pure/collections", "std", "impure", "pure/concurrency",
        ]
        actual_modules = set()
        for subdir in stdlib_dirs:
            full = os.path.join(lib_root, subdir)
            if not os.path.isdir(full):
                continue
            for fname in os.listdir(full):
                if fname.endswith(".nim"):
                    actual_modules.add(fname[:-4])

        # Extract the scanner's hardcoded list
        scanner_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "cartograph",
            "languages", "scanners", "nim_scanner.nim",
        )
        scanner_src = open(scanner_path).read()
        # Pull all quoted strings from the nimStdlib block
        start = scanner_src.index("const nimStdlib = [")
        end = scanner_src.index("].toHashSet()", start)
        block = scanner_src[start:end]
        scanner_modules = set()
        for m in _re.findall(r'"([^"]+)"', block):
            # Strip std/ prefix to get the bare module name
            bare = m.split("/")[-1]
            scanner_modules.add(bare)

        # Internal/private modules that aren't meant for user import
        internal = {"hashcommon", "tableimpl", "setimpl", "rtarrays"}
        actual_public = actual_modules - internal

        missing = actual_public - scanner_modules
        assert not missing, (
            f"Nim stdlib modules missing from nim_scanner.nim nimStdlib list: "
            f"{sorted(missing)}\n"
            f"Update the hardcoded list in scanners/nim_scanner.nim"
        )


# ---------------------------------------------------------------------------
# 3. SHARED VALIDATION TESTS
# ---------------------------------------------------------------------------

class TestDepPinning:
    """_check_dep_pinning is shared across all engines."""

    @pytest.mark.parametrize("lang,engine_cls", [
        ("python", PythonEngine),
        ("javascript", JavaScriptEngine),
        ("nim", NimEngine),
        ("systemverilog", SystemVerilogEngine),
    ])
    def test_unpinned_dep_fails(self, tmp_path, lang, engine_cls):
        if lang in NEEDS_TOOL:
            _skip_if_missing(lang)
        wdir = _make_widget(tmp_path, lang, f"mod.{EXT[lang]}",
                            CLEAN[lang][0])
        result = engine_cls().validate_widget(wdir, ["somelib"])
        assert result["passed"] is False
        assert "version pin" in result["error"] or "version" in result["error"].lower()

    @pytest.mark.parametrize("lang,engine_cls", [
        ("python", PythonEngine),
        ("javascript", JavaScriptEngine),
        ("nim", NimEngine),
        ("systemverilog", SystemVerilogEngine),
    ])
    def test_pinned_dep_passes_pinning(self, tmp_path, lang, engine_cls):
        if lang in NEEDS_TOOL:
            _skip_if_missing(lang)
        wdir = _make_widget(tmp_path, lang, f"mod.{EXT[lang]}",
                            CLEAN[lang][0])
        result = engine_cls().validate_widget(wdir, ["somelib>=1.0.0"])
        # Should not fail due to pinning (may fail for other reasons)
        if not result["passed"]:
            assert "version pin" not in result.get("error", "")


class TestOrchestrator:
    """The contamination.py module delegates to the right engine."""

    def test_python_delegation(self, tmp_path):
        wdir = _make_widget(tmp_path, "python", "mod.py",
                            'LOG = "/home/user/logs"\n')
        result = scan_contamination(wdir)
        assert any("path" in b.lower() for b in result["blocks"])

    def test_js_delegation(self, tmp_path):
        if not shutil.which("node"):
            pytest.skip("Node.js not installed")
        wdir = _make_widget(tmp_path, "javascript", "mod.js",
                            "const api_key = 'sk-abc123verylongkey'\n")
        result = scan_contamination(wdir)
        assert any("credential" in b.lower() for b in result["blocks"])

    def test_nim_delegation(self, tmp_path):
        if not shutil.which("nim"):
            pytest.skip("Nim not installed")
        wdir = _make_widget(tmp_path, "nim", "mod.nim",
                            'let api_key = "sk-abc123verylongkey"\n')
        result = scan_contamination(wdir)
        assert any("credential" in b.lower() for b in result["blocks"])

    def test_sv_delegation(self, tmp_path):
        if not shutil.which("iverilog"):
            pytest.skip("iverilog not installed")
        wdir = _make_widget(tmp_path, "systemverilog", "mod.sv",
                            "module m;\n    initial begin\n    end\nendmodule\n")
        result = scan_contamination(wdir)
        assert any("initial" in b.lower() for b in result["blocks"])

    def test_missing_manifest_returns_empty(self, tmp_path):
        result = scan_contamination(str(tmp_path))
        assert result["warnings"] == []
        assert len(result["blocks"]) == 1
        assert "widget.json" in result["blocks"][0]

    def test_unknown_language_uses_base_fallback(self, tmp_path):
        wdir = _make_widget(tmp_path, "lua", "mod.lua",
                            'LOG = "/home/user/logs/app.log"\n')
        result = scan_contamination(wdir)
        assert any("Absolute path" in b for b in result["blocks"])


class TestBaseFallback:
    """The base LanguageEngine provides regex fallback for checks 1-4.

    Check 5 (sleep) is explicitly NOT covered by regex - it requires
    native tooling per the standard in base.py.
    """

    def _scan(self, tmp_path, src_code, ext="txt"):
        wdir = _make_widget(tmp_path, "base", f"module.{ext}", src_code)
        engine = LanguageEngine()
        engine.file_ext = ext
        return engine.scan_contamination(wdir, {"language": "base"})

    def test_abs_path_caught(self, tmp_path):
        result = self._scan(tmp_path, 'x = "/home/user/data"\n')
        assert any("Absolute path" in b for b in result["blocks"])

    def test_credential_caught(self, tmp_path):
        result = self._scan(tmp_path, 'api_key = "sk-abc123verylongkey"\n')
        assert any("credential" in b.lower() for b in result["blocks"])

    def test_url_caught(self, tmp_path):
        result = self._scan(tmp_path,
                            'url = "https://api.company.com/v2/data"\n')
        assert any("URL" in w for w in result["warnings"])

    def test_ip_caught(self, tmp_path):
        result = self._scan(tmp_path, 'host = "192.168.1.50"\n')
        assert any("IP" in b for b in result["blocks"])

    def test_hardcoded_number_warns(self, tmp_path):
        result = self._scan(tmp_path, "TIMEOUT = 30\n")
        assert any("Hardcoded value" in w for w in result["warnings"])

    def test_credential_in_tests_warns(self, tmp_path):
        wdir = _make_widget(tmp_path, "base", "module.txt",
                            "x = 1\n")
        engine = LanguageEngine()
        engine.file_ext = "txt"
        _write(os.path.join(wdir, "tests", "test_module.txt"),
               'password = "fake_test_password_123"\n')
        result = engine.scan_contamination(wdir, {"language": "base"})
        assert not any("credential" in b.lower() for b in result["blocks"])
        assert any("credential" in w.lower() for w in result["warnings"])

    def test_clean_passes(self, tmp_path):
        result = self._scan(tmp_path, "x = compute()\n")
        assert result["blocks"] == []
        assert result["warnings"] == []

    def test_unreadable_source_file_blocks(self, tmp_path):
        wdir = _make_widget(tmp_path, "base", "module.txt", "x = 1\n")
        engine = LanguageEngine()
        engine.file_ext = "txt"
        target = os.path.join(wdir, "src", "module.txt")
        real_open = open

        def fake_open(path, *args, **kwargs):
            if path == target:
                raise OSError("permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=fake_open):
            result = engine.scan_contamination(wdir, {"language": "base"})

        assert any("could not read source file" in b.lower() for b in result["blocks"])

    def test_abs_path_in_comment_not_flagged(self, tmp_path):
        result = self._scan(tmp_path, '// Example: x = "/home/user/.config/app"\n')
        assert not any("Absolute path" in b for b in result["blocks"])

    def test_version_string_not_flagged_as_ip(self, tmp_path):
        # "1.2.3.4" style version strings should not trigger IP detection
        result = self._scan(tmp_path, 'VERSION = "1.2.3.4"\n')
        assert not any("IP" in b for b in result["blocks"])

    def test_real_ip_still_caught(self, tmp_path):
        # An actual IP with multi-digit octets must still be blocked
        result = self._scan(tmp_path, 'host = "192.168.1.50"\n')
        assert any("IP" in b for b in result["blocks"])

    def test_credential_in_comment_still_caught(self, tmp_path):
        # Credentials left in comments (even as examples) must be flagged
        result = self._scan(tmp_path, '// api_key = "sk-abc123verylongkey"\n')
        assert any("credential" in b.lower() for b in result["blocks"])


@pytest.mark.nim
class TestNimRiskyImportIsWarning:
    def test_std_os_is_warning_not_error(self, tmp_path):
        _skip_if_missing("nim")
        result = _scan(tmp_path, "nim", "nim", "import std/os\nproc f*() = discard\n")
        assert not any("risky" in b.lower() for b in result["blocks"])
        assert any("risky" in w.lower() or "i/o" in w.lower() or "network" in w.lower()
                   for w in result["warnings"])

    def test_std_httpclient_is_warning_not_error(self, tmp_path):
        _skip_if_missing("nim")
        result = _scan(tmp_path, "nim", "nim", "import std/httpclient\nproc f*() = discard\n")
        assert not any("risky" in b.lower() for b in result["blocks"])
        assert any("risky" in w.lower() or "i/o" in w.lower() or "network" in w.lower()
                   for w in result["warnings"])


@pytest.mark.python
class TestPythonAbsPathCommentExclusion:
    def test_abs_path_in_comment_not_flagged(self, tmp_path):
        from cartograph.languages.python import PythonEngine
        wdir = _make_widget(tmp_path, "python", "mod.py",
                            '# Example: path = "/home/user/.config"\ndef f(): pass\n')
        engine = PythonEngine()
        result = engine.scan_contamination(wdir, {"dependencies": []})
        assert not any("Absolute path" in b for b in result["blocks"])

    def test_abs_path_in_code_still_caught(self, tmp_path):
        from cartograph.languages.python import PythonEngine
        wdir = _make_widget(tmp_path, "python", "mod.py",
                            'path = "/home/user/.config/app"\n')
        engine = PythonEngine()
        result = engine.scan_contamination(wdir, {"dependencies": []})
        assert any("Absolute path" in b for b in result["blocks"])

    def test_version_string_not_flagged_as_ip(self, tmp_path):
        from cartograph.languages.python import PythonEngine
        wdir = _make_widget(tmp_path, "python", "mod.py",
                            'VERSION = "1.2.3.4"\n')
        engine = PythonEngine()
        result = engine.scan_contamination(wdir, {"dependencies": []})
        assert not any("IP" in b for b in result["blocks"])

    def test_credential_in_comment_still_caught(self, tmp_path):
        from cartograph.languages.python import PythonEngine
        wdir = _make_widget(tmp_path, "python", "mod.py",
                            '# api_key = "sk-abc123verylongkey"\ndef f(): pass\n')
        engine = PythonEngine()
        result = engine.scan_contamination(wdir, {"dependencies": []})
        assert any("credential" in b.lower() for b in result["blocks"])


@pytest.mark.openscad
class TestOpenSCADContamination:
    """OpenSCAD-specific contamination checks."""

    def _scan(self, tmp_path, src_content):
        from cartograph.languages.openscad import OpenSCADEngine
        wdir = tmp_path / "widget"
        (wdir / "src").mkdir(parents=True)
        (wdir / "tests").mkdir()
        (wdir / "examples").mkdir()
        (wdir / "src" / "mod.scad").write_text(src_content)
        engine = OpenSCADEngine()
        return engine.scan_contamination(str(wdir), {"dependencies": []})

    # --- top-level geometry ---

    def test_top_level_cube_blocks(self, tmp_path):
        result = self._scan(tmp_path, 'module m(w=10) { cube([w,w,w]); }\ncube([5,5,5]);\n')
        assert any("top-level geometry" in b.lower() for b in result["blocks"])

    def test_top_level_sphere_blocks(self, tmp_path):
        result = self._scan(tmp_path, 'module m(r=5) { sphere(r); }\nsphere(r=3);\n')
        assert any("top-level geometry" in b.lower() for b in result["blocks"])

    def test_geometry_inside_module_is_clean(self, tmp_path):
        result = self._scan(tmp_path, 'module m(w=10) { cube([w,w,w]); }\n')
        assert not any("top-level geometry" in b.lower() for b in result["blocks"])

    # --- parameters without defaults ---

    def test_param_without_default_blocks(self, tmp_path):
        result = self._scan(tmp_path, 'module m(width, height=10) { cube([width,height,5]); }\n')
        assert any("no default" in b.lower() for b in result["blocks"])
        assert any("width" in b for b in result["blocks"])

    def test_all_params_have_defaults_is_clean(self, tmp_path):
        result = self._scan(tmp_path, 'module m(width=20, height=10) { cube([width,height,5]); }\n')
        assert not any("no default" in b.lower() for b in result["blocks"])

    def test_no_params_is_clean(self, tmp_path):
        result = self._scan(tmp_path, 'module m() { cube([10,10,10]); }\n')
        assert not any("no default" in b.lower() for b in result["blocks"])

    # --- parameter unit comments ---

    def test_param_without_unit_comment_warns(self, tmp_path):
        result = self._scan(tmp_path, 'module m(width=20, height=10) { cube([width,height,5]); }\n')
        assert any("unit comment" in w.lower() for w in result["warnings"])

    def test_multiline_params_with_comments_clean(self, tmp_path):
        src = 'module m(\n    width  = 20,  // mm\n    height = 10   // mm\n) { cube([width,height,5]); }\n'
        result = self._scan(tmp_path, src)
        assert not any("unit comment" in w.lower() for w in result["warnings"])

    # --- existing checks still work ---

    def test_absolute_path_blocks(self, tmp_path):
        result = self._scan(tmp_path, 'module m(w=10) { cube([w,w,w]); }\nuse </abs/path/lib.scad>\n')
        assert any("absolute path" in b.lower() for b in result["blocks"])

    def test_credential_blocks(self, tmp_path):
        result = self._scan(tmp_path, 'module m(w=10) { cube([w,w,w]); }\napi_key = "sk-secret123abc";\n')
        assert any("credential" in b.lower() for b in result["blocks"])


@pytest.mark.systemverilog
class TestSystemVerilogContamination:
    """SystemVerilog-specific contamination checks."""

    @pytest.fixture(autouse=True)
    def _require_iverilog(self):
        if not shutil.which("iverilog"):
            pytest.skip("iverilog not installed")

    def _scan(self, tmp_path, src_content, dependencies=None):
        wdir = tmp_path / "widget"
        (wdir / "src").mkdir(parents=True)
        (wdir / "tests").mkdir()
        (wdir / "examples").mkdir()
        (wdir / "src" / "mod.sv").write_text(src_content)
        engine = SystemVerilogEngine()
        return engine.scan_contamination(
            str(wdir), {"language": "systemverilog",
                        "dependencies": dependencies or []})

    # --- clean code ---

    def test_clean_module_no_findings(self, tmp_path):
        result = self._scan(tmp_path,
            "module m #(parameter int W = 8)(\n"
            "    input logic clk, input logic rst_n,\n"
            "    input logic [W-1:0] d, output logic [W-1:0] q\n"
            ");\n    always_ff @(posedge clk) begin\n"
            "        if (!rst_n) q <= '0; else q <= d;\n"
            "    end\nendmodule\n")
        assert result["blocks"] == [], f"unexpected blocks: {result['blocks']}"

    # --- vendor primitives ---

    def test_vendor_primitive_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m; BUFG clk_buf (.I(clk), .O(buf_clk)); endmodule\n")
        assert any("vendor" in b.lower() for b in result["blocks"])

    def test_vendor_primitive_allowed_with_dep(self, tmp_path):
        result = self._scan(tmp_path,
            "module m; BUFG clk_buf (.I(clk), .O(buf_clk)); endmodule\n",
            dependencies=["xilinx-unisim"])
        assert not any("vendor" in b.lower() for b in result["blocks"])

    def test_altera_primitive_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m; ALTPLL #(.WIDTH(8)) pll (.inclk0(clk)); endmodule\n")
        assert any("vendor" in b.lower() for b in result["blocks"])

    def test_altera_allowed_with_dep(self, tmp_path):
        result = self._scan(tmp_path,
            "module m; ALTPLL #(.WIDTH(8)) pll (.inclk0(clk)); endmodule\n",
            dependencies=["altera-ip"])
        assert not any("vendor" in b.lower() for b in result["blocks"])

    # --- initial blocks ---

    def test_initial_block_in_src_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    initial begin\n        d_out = '0;\n    end\nendmodule\n")
        assert any("initial" in b.lower() for b in result["blocks"])

    # --- #delay ---

    def test_delay_in_src_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    always_ff @(posedge clk) begin\n"
            "        #10 q <= d;\n    end\nendmodule\n")
        assert any("delay" in b.lower() for b in result["blocks"])

    # --- timescale ---

    def test_timescale_in_src_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "`timescale 1ns/1ps\nmodule m; endmodule\n")
        assert any("timescale" in b.lower() for b in result["blocks"])

    # --- legacy always ---

    def test_legacy_always_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    always @(posedge clk) begin\n"
            "        q <= d;\n    end\nendmodule\n")
        assert any("always @" in b or "Verilog-2001" in b for b in result["blocks"])

    # --- $display family ---

    def test_display_in_src_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    always_ff @(posedge clk) begin\n"
            "        $display(\"debug\");\n        q <= d;\n"
            "    end\nendmodule\n")
        assert any("display" in b.lower() for b in result["blocks"])

    def test_monitor_in_src_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    always_comb begin\n"
            "        $monitor(\"watch\");\n    end\nendmodule\n")
        assert any("monitor" in b.lower() for b in result["blocks"])

    # --- $readmemh hardcoded path ---

    def test_readmemh_hardcoded_path_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n    logic [7:0] mem [0:255];\n"
            "    always_comb $readmemh(\"/data/rom.hex\", mem);\n"
            "endmodule\n")
        assert any("readmemh" in b.lower() for b in result["blocks"])

    # --- blocking/non-blocking assignment ---

    def test_blocking_in_always_ff_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m(input logic clk, input logic d, output logic q);\n"
            "    always_ff @(posedge clk) begin\n"
            "        q = d;\n"
            "    end\nendmodule\n")
        assert any("blocking" in b.lower() and "always_ff" in b
                    for b in result["blocks"])

    def test_nonblocking_in_always_comb_blocks(self, tmp_path):
        result = self._scan(tmp_path,
            "module m(input logic a, output logic b);\n"
            "    always_comb begin\n"
            "        b <= a;\n"
            "    end\nendmodule\n")
        assert any("non-blocking" in b.lower() and "always_comb" in b
                    for b in result["blocks"])

    def test_for_loop_in_always_ff_not_false_positive(self, tmp_path):
        result = self._scan(tmp_path,
            "module m #(parameter int D = 4)(\n"
            "    input logic clk, input logic rst_n,\n"
            "    output logic [7:0] s [0:D-1]\n"
            ");\n    always_ff @(posedge clk) begin\n"
            "        if (!rst_n)\n"
            "            for (int i = 0; i < D; i++) s[i] <= '0;\n"
            "    end\nendmodule\n")
        assert not any("blocking" in b.lower() for b in result["blocks"])

    def test_typedef_enum_not_false_positive(self, tmp_path):
        result = self._scan(tmp_path,
            "module m;\n"
            "    typedef enum logic [1:0] {\n"
            "        IDLE = 2'b00, RUN = 2'b01\n"
            "    } state_t;\n"
            "    state_t st;\nendmodule\n")
        assert not any("hardcoded" in w.lower() for w in result["warnings"])

    # --- comments don't false-positive ---

    def test_vendor_in_comment_not_flagged(self, tmp_path):
        result = self._scan(tmp_path,
            "// This replaces a LUT6 with generic logic\n"
            "/* Previously used BUFG */\n"
            "module m; endmodule\n")
        assert not any("vendor" in b.lower() for b in result["blocks"])
