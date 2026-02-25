#!/usr/bin/env python3
"""
Overnight Widget Factory
Generates widgets autonomously using local LLM or xAI Grok API
"""

import asyncio
import json
import subprocess
import sys
import re
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Union
from difflib import unified_diff

# Load .env file if present
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Add client paths
sys.path.insert(0, str(Path(__file__).parent / "cartographer/widgets/logic.llamaclient-python"))
sys.path.insert(0, str(Path(__file__).parent / "cartographer/widgets/logic.grokclient-python"))
from src.llama_client import LlamaClient
from src.grok_client import GrokClient


# ============================================================================
# CONFIGURATION
# ============================================================================
LLAMA_URL = "http://localhost:58080/v1"
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
# Sequential language order for multi-language implementation
LANGUAGE_ORDER = ["python", "javascript", "typescript", "go", "rust"]
MAX_VALIDATION_RETRIES = 3  # Reduced for faster testing/observation
TARGET_WIDGET_COUNT = 100
WORKFLOW_PATH = Path(".agent/widget_creation_workflow.md")
BRAINSTORM_PATH = Path(".agent/widget_brainstorm_prompt.md")
MODEL_PROFILES_PATH = Path("model_profiles.json")
FAILED_DIR = Path("./failed_widgets")


# ============================================================================
# LANGUAGE DESIGN GUIDELINES
# ============================================================================
LANGUAGE_GUIDELINES = {
    "python": {
        "testing_framework": "pytest",
        "file_structure": """
        - src/{module_name}.py (main implementation)
        - tests/test_{module_name}.py (pytest tests)
        - examples/basic_usage.py (usage example)
        """,
        "critical_patterns": """
        1. IMPORTS IN TESTS (MANDATORY):
           ```python
           import sys
           from pathlib import Path
           sys.path.insert(0, str(Path(__file__).parent.parent))
           from src.{module_name} import {ClassName}
           ```

        2. ASYNC TESTS:
           - Use @pytest.mark.asyncio decorator
           - Always await async methods
           - CRITICAL: Clean up background tasks in try/finally:
             ```python
             @pytest.mark.asyncio
             async def test_something():
                 widget = AsyncWidget()
                 await widget.start()
                 try:
                     # test code
                 finally:
                     await widget.stop()
                     await asyncio.sleep(0.1)  # Let event loop finish
             ```

        3. ASYNC FIXTURES:
           - Fixture itself should NOT be async
           - Only test function should be async
           - Use @pytest.fixture decorator (not @pytest.fixture + async def)

        4. COMMON PITFALLS:
           - Missing sys.path setup → ModuleNotFoundError
           - Forgetting 'await' on async methods
           - Not cleaning up background tasks → Event loop errors
           - Making fixtures async when they shouldn't be
        """,
        "validation_command": "pytest tests/"
    },

    "javascript": {
        "testing_framework": "node:assert (built-in)",
        "file_structure": """
        - src/{ClassName}.js (main implementation, PascalCase filename)
        - tests/controller.node.mjs (actual Node.js tests)
        - tests/test_{module_name}.py (pytest wrapper that runs Node)
        - examples/basic_usage.js (usage example)
        """,
        "critical_patterns": """
        1. TEST FILE STRUCTURE (controller.node.mjs):
           ```javascript
           import assert from 'node:assert/strict';
           import { ClassName } from '../src/ClassName.js';

           async function testBasicFunctionality() {
               const instance = new ClassName();
               const result = await instance.someMethod();
               assert.equal(result, expectedValue);
           }

           async function testEdgeCase() {
               // Another test...
           }

           async function run() {
               await testBasicFunctionality();
               await testEdgeCase();
           }

           run()
               .then(() => console.log('All tests passed.'))
               .catch((error) => { console.error(error); process.exit(1); });
           ```

        2. IMPORTS:
           - Use Node's built-in assert: import assert from 'node:assert/strict'
           - Import widget from src/ using ES6 modules
           - NO vitest, NO jest - just Node.js native assertions

        3. TEST PATTERN:
           - Each test is an async function
           - Use assert.equal(), assert.ok(), assert.throws(), assert.rejects()
           - Collect all tests in a run() function
           - Call run() at the end with .then/.catch for exit code

        4. COMMON PITFALLS:
           - Forgetting to await async methods
           - Not calling process.exit(1) on failure
           - Missing the run() wrapper function
        """,
        "validation_command": "pytest tests/"
    },

    "typescript": {
        "testing_framework": "node:assert (built-in, via ts-node or transpile)",
        "file_structure": """
        - src/{ClassName}.ts (main implementation, PascalCase filename)
        - tests/controller.node.mjs (actual Node.js tests - compiled or raw JS)
        - tests/test_{module_name}.py (pytest wrapper that runs Node)
        - examples/basic_usage.ts (usage example)
        """,
        "critical_patterns": """
        1. TEST FILE STRUCTURE (controller.node.mjs - use JavaScript for tests):
           ```javascript
           import assert from 'node:assert/strict';
           // Import from compiled JS or use dynamic import for TS
           import { ClassName } from '../src/ClassName.js';

           async function testBasicFunctionality() {
               const instance = new ClassName();
               const result = await instance.someMethod();
               assert.equal(result, expectedValue);
           }

           async function run() {
               await testBasicFunctionality();
           }

           run()
               .then(() => console.log('All tests passed.'))
               .catch((error) => { console.error(error); process.exit(1); });
           ```

        2. IMPORTS:
           - Use Node's built-in assert: import assert from 'node:assert/strict'
           - Import widget from src/ (assuming compiled to JS or using ts-node)
           - NO vitest, NO jest - just Node.js native assertions

        3. TYPE SAFETY (in src/ files):
           - Define interfaces for all public APIs
           - Use strict mode
           - Avoid 'any' - use proper types
           - Export types for consumers

        4. COMMON PITFALLS:
           - Forgetting to compile TS before running tests
           - Not calling process.exit(1) on failure
           - Missing type exports
        """,
        "validation_command": "pytest tests/"
    },

    "go": {
        "testing_framework": "testing (stdlib)",
        "file_structure": """
        - src/{module_name}.go (main implementation)
        - tests/{module_name}_test.go (go tests)
        - examples/basic_usage.go (usage example)
        - go.mod (automatically generated - defines module)
        """,
        "critical_patterns": """
        1. IMPORTS IN TESTS (MANDATORY - USE GO SYNTAX):
           ```go
           package widgetname_test

           import (
               "testing"
               // Import from src/ using go.mod module path
               widget "github.com/cartographer/{widget-name}/src"
           )

           // NOT Python imports, NOT JavaScript imports
           // Use Go module path from go.mod
           ```

           ⚠️ NEVER use Python import syntax (no 'import sys', no 'from pathlib')
           ⚠️ ALWAYS use Go module imports with package name

        2. TEST STRUCTURE:
           ```go
           func TestBasicUsage(t *testing.T) {
               // Table-driven tests preferred
               tests := []struct {
                   name string
                   input string
                   want string
               }{
                   {"case1", "input", "expected"},
               }

               for _, tt := range tests {
                   t.Run(tt.name, func(t *testing.T) {
                       // test logic
                   })
               }
           }
           ```

        2. ERROR HANDLING:
           - Always check errors: if err != nil { return err }
           - Use error wrapping: fmt.Errorf("context: %w", err)

        3. CONCURRENCY:
           - Use channels and goroutines properly
           - Always wait for goroutines to finish
           - Use context for cancellation

        4. COMMON PITFALLS:
           - Ignoring errors
           - Not cleaning up goroutines
           - Race conditions with shared state
        """,
        "validation_command": "go test ./..."
    },

    "rust": {
        "testing_framework": "cargo test",
        "file_structure": """
        - src/lib.rs (main implementation - MUST be lib.rs for library crate)
        - tests/integration_test.rs (integration tests)
        - examples/basic_usage.rs (usage example)
        - Cargo.toml (automatically generated - defines package)
        """,
        "critical_patterns": """
        1. LIBRARY STRUCTURE (MANDATORY - USE RUST SYNTAX):
           ```rust
           // src/lib.rs - All public items need 'pub' keyword
           pub struct Widget {
               field: String,
           }

           pub fn new() -> Widget {
               Widget { field: String::from("value") }
           }
           ```

           ⚠️ NEVER use Python import syntax (no 'import sys', no 'from pathlib')
           ⚠️ ALWAYS use Rust use statements

        2. IMPORTS IN TESTS (MANDATORY):
           UNIT TESTS (in src/lib.rs):
           ```rust
           #[cfg(test)]
           mod tests {
               use super::*;  // Import from parent module

               #[test]
               fn test_basic() {
                   let widget = Widget::new();
                   assert_eq!(widget.method(), expected);
               }
           }
           ```

           INTEGRATION TESTS (in tests/integration_test.rs):
           ```rust
           // Import the crate by name (from Cargo.toml)
           use widget_name::Widget;

           #[test]
           fn integration_test() {
               let w = Widget::new();
               assert!(w.is_valid());
           }
           ```

        3. ERROR HANDLING:
           - Use Result<T, E> for fallible operations
           - Use Option<T> for optional values
           - Propagate errors with ? operator
           - Define custom error types if needed

        4. OWNERSHIP & LIFETIMES:
           - Understand borrowing rules
           - Use lifetimes when needed
           - Clone only when necessary
           - Prefer &str over String for parameters

        5. COMMON PITFALLS:
           - Fighting the borrow checker (restructure code instead)
           - Unnecessary clones (use references)
           - Not making items pub (must be pub for external use)
           - Using mod instead of pub mod for submodules
        """,
        "validation_command": "cargo test"
    }
}


# ============================================================================
# Widget Factory
# ============================================================================
class WidgetFactory:
    def __init__(self, llama_url: str = LLAMA_URL, model_profile: str = "default", debug: bool = False):
        self.generated_count = 0
        self.log_file = Path(f"./factory_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
        self.workflow = WORKFLOW_PATH.read_text()
        self.brainstorm_prompt = BRAINSTORM_PATH.read_text()

        # Debug mode
        self.debug = debug
        if self.debug:
            self.debug_file = Path(f"./factory_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            self.debug_file.write_text(f"=== WIDGET FACTORY DEBUG LOG ===\nStarted: {datetime.now().isoformat()}\n\n")
            self.log(f"DEBUG MODE ENABLED - Logging to {self.debug_file}", "INFO")

        # Load model profile
        self.profile = self._load_profile(model_profile)
        self.log(f"Using model profile: {self.profile['name']}", "INFO")

        # Initialize appropriate client based on profile
        if self.profile.get("requires_api_key"):
            # Use GrokClient for xAI profiles
            api_key = XAI_API_KEY
            if not api_key:
                raise ValueError(f"Profile '{model_profile}' requires XAI_API_KEY in .env file")
            model_name = self.profile.get("model_name", "grok-4-1-fast-non-reasoning")
            self.client = GrokClient(api_key=api_key, default_model=model_name, timeout=600)
            self.log(f"Using GrokClient with model: {model_name}", "INFO")
        else:
            # Use LlamaClient for local LLM profiles
            self.client = LlamaClient(base_url=llama_url, timeout=600)
            self.log(f"Using LlamaClient at: {llama_url}", "INFO")

    def _load_profile(self, profile_name: str) -> Dict:
        """Load model profile configuration"""
        try:
            if MODEL_PROFILES_PATH.exists():
                profiles = json.loads(MODEL_PROFILES_PATH.read_text())
                if profile_name in profiles:
                    return profiles[profile_name]
                else:
                    self.log(f"Profile '{profile_name}' not found, using default", "WARN")
                    return profiles.get("default", self._default_profile())
            else:
                self.log("model_profiles.json not found, using default", "WARN")
                return self._default_profile()
        except Exception as e:
            self.log(f"Failed to load profiles: {e}, using default", "WARN")
            return self._default_profile()

    def _default_profile(self) -> Dict:
        """Fallback default profile"""
        return {
            "name": "Default",
            "thinking_tags": [],
            "strip_thinking": False,
            "temperature_brainstorm": 0.9,
            "temperature_code": 0.3,
            "temperature_fix": 0.2,
            "max_tokens_brainstorm": 2000,
            "max_tokens_code": 8000,
            "max_tokens_fix": 8000
        }

    def _get_file_extension(self, language: str) -> str:
        """Convert language name to proper file extension"""
        extensions = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "java": "java",
            "go": "go",
            "rust": "rs",
            "c": "c",
            "cpp": "cpp",
            "csharp": "cs",
            "ruby": "rb",
            "php": "php",
            "swift": "swift",
            "kotlin": "kt",
        }
        return extensions.get(language.lower(), language.lower())

    def _get_language_guidelines(self, language: str) -> str:
        """Get comprehensive design guidelines for a language"""
        guidelines = LANGUAGE_GUIDELINES.get(language.lower())
        if not guidelines:
            return f"No specific guidelines for {language}. Follow general best practices."

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 {language.upper()} DESIGN GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📦 Testing Framework: {guidelines['testing_framework']}

📁 File Structure:
{guidelines['file_structure']}

⚡ Critical Patterns & Pitfalls:
{guidelines['critical_patterns']}

✅ Validation Command: {guidelines['validation_command']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  THESE ARE NOT SUGGESTIONS - FOLLOW EXACTLY AS SPECIFIED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    def _calculate_filenames(self, widget_id: str, language: str) -> dict:
        """Calculate standard filenames based on widget_id and language

        Returns dict with: src_filename, test_filename, example_filename
        For JS/TS: also includes test_wrapper_filename (Python pytest wrapper)
        """
        file_ext = self._get_file_extension(language)

        # Convert widget_id to valid module name (replace dashes/dots with underscores)
        module_name = widget_id.replace('-', '_').replace('.', '_')

        result = {
            "src_filename": f"{module_name}.{file_ext}",
            "test_filename": f"test_{module_name}.{file_ext}",
            "example_filename": f"basic_usage.{file_ext}"
        }

        # JS/TS use controller.node.mjs pattern with Python wrapper
        if language.lower() in ["javascript", "typescript"]:
            result["test_filename"] = "controller.node.mjs"  # Actual JS tests
            result["test_wrapper_filename"] = f"test_{module_name}.py"  # Python pytest wrapper

        # Go expects *_test.go suffix, not test_* prefix
        if language.lower() == "go":
            result["test_filename"] = f"{module_name}_test.go"

        return result

    def _generate_js_test_wrapper(self, widget_id: str) -> str:
        """Generate Python pytest wrapper for JS/TS tests.

        This wrapper runs the actual JS tests (controller.node.mjs) via Node.js,
        allowing pytest to be the unified test runner for all languages.
        """
        module_name = widget_id.replace('-', '_').replace('.', '_')
        return f'''import shutil
import subprocess
from pathlib import Path

import pytest


def test_{module_name}_node_suite():
    """Run JavaScript/TypeScript tests via Node.js"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available in this environment.")

    tests_dir = Path(__file__).parent
    script_path = tests_dir / "controller.node.mjs"

    if not script_path.exists():
        pytest.fail(f"Test controller not found: {{script_path}}")

    result = subprocess.run(
        [node, str(script_path)],
        cwd=tests_dir,
        capture_output=True,
        text=True,
        timeout=30
    )

    assert result.returncode == 0, result.stderr or result.stdout
'''

    def _generate_cargo_toml(self, widget_id: str, spec: Dict) -> str:
        """Generate Cargo.toml for Rust widgets"""
        # Convert widget-id to valid crate name (replace dashes with underscores)
        crate_name = widget_id.replace('-', '_').replace('.', '_')

        # Extract dependencies from spec
        dependencies = spec.get('dependencies', [])
        dep_section = ""
        if dependencies:
            dep_lines = []
            for dep in dependencies:
                if isinstance(dep, dict):
                    # Structured dependency: {name: "tokio", version: "1.0", features: ["full"]}
                    name = dep.get('name', '')
                    version = dep.get('version', '*')
                    features = dep.get('features', [])
                    if features:
                        dep_lines.append(f'{name} = {{ version = "{version}", features = {features} }}')
                    else:
                        dep_lines.append(f'{name} = "{version}"')
                else:
                    # Simple string dependency
                    dep_lines.append(f'{dep} = "*"')
            if dep_lines:
                dep_section = "\n".join(dep_lines)

        cargo_toml = f"""[package]
name = "{crate_name}"
version = "1.0.0"
edition = "2021"

[lib]
path = "src/lib.rs"

[dependencies]
{dep_section if dep_section else "# Add dependencies here"}

[[example]]
name = "basic_usage"
path = "examples/basic_usage.rs"
"""
        return cargo_toml

    def _generate_go_mod(self, widget_id: str, spec: Dict) -> str:
        """Generate go.mod for Go widgets"""
        # Convert widget-id to valid module path
        module_name = widget_id.replace('_', '-')  # Go prefers dashes in module paths

        # Extract dependencies from spec
        dependencies = spec.get('dependencies', [])
        require_section = ""
        if dependencies:
            require_lines = []
            for dep in dependencies:
                if isinstance(dep, dict):
                    # Structured dependency: {name: "github.com/pkg/errors", version: "v0.9.1"}
                    name = dep.get('name', '')
                    version = dep.get('version', 'latest')
                    require_lines.append(f"\t{name} {version}")
                else:
                    # Simple string dependency (assume it's a path)
                    require_lines.append(f"\t{dep} latest")
            if require_lines:
                require_section = "require (\n" + "\n".join(require_lines) + "\n)"

        go_mod = f"""module github.com/cartographer/{module_name}

go 1.21

{require_section if require_section else "// Add dependencies here with: go get <package>"}
"""
        return go_mod

    def _extract_class_name_from_source(self, source_code: str) -> str:
        """Extract the main class name from source code"""
        import re

        # Try to find class definition
        class_match = re.search(r'class\s+(\w+)[\(:]', source_code)
        if class_match:
            return class_match.group(1)

        # Fallback: return empty string
        return ""

    def _ensure_test_imports_python(self, test_content: str, module_name: str, class_name: str) -> str:
        """PYTHON ONLY: Ensure test file has correct sys.path setup and imports.

        This is a safety net - even if LLM forgets, we inject the imports.
        """
        # The required sys.path setup (always identical)
        required_syspath = """import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))"""

        # The required src import (changes per widget)
        required_import = f"from src.{module_name} import {class_name}"

        # Check if both are present
        has_syspath = "sys.path.insert(0, str(Path(__file__).parent.parent))" in test_content
        has_src_import = f"from src.{module_name} import" in test_content

        if has_syspath and has_src_import:
            if self.debug:
                self.log(f"  ✅ Python test imports already correct", "INFO")
            return test_content

        self.log(f"  🔧 INJECTING missing Python test imports (syspath={not has_syspath}, src_import={not has_src_import})", "WARN")

        # Remove any bad imports like "from ../src.X" or "from ..src.X"
        import re
        test_content = re.sub(r'from\s+\.\./?src\.(\w+)\s+import', r'from src.\1 import', test_content)

        # Split into lines
        lines = test_content.split('\n')

        # Find where to inject (before first non-comment, non-blank line)
        inject_index = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and not stripped.startswith('"""') and not stripped.startswith("'''"):
                inject_index = i
                break

        # Build injection block
        injection = []
        if not has_syspath:
            injection.extend([
                "import sys",
                "from pathlib import Path",
                "sys.path.insert(0, str(Path(__file__).parent.parent))",
                ""
            ])

        if not has_src_import:
            injection.append(required_import)
            injection.append("")

        # Insert at the beginning
        lines = injection + lines

        return '\n'.join(lines)

    def _ensure_test_imports_javascript(self, test_content: str, module_name: str, class_name: str) -> str:
        """JAVASCRIPT ONLY: Ensure test file (controller.node.mjs) has correct Node assert imports."""
        import re

        # Check for Node assert import
        has_assert = "from 'node:assert" in test_content or 'from "node:assert' in test_content
        has_src_import = f"from '../src/" in test_content or f'from "../src/' in test_content

        # Remove any Python imports that shouldn't be there
        test_content = re.sub(r'import sys\s*\n', '', test_content)
        test_content = re.sub(r'from pathlib import Path\s*\n', '', test_content)
        test_content = re.sub(r'sys\.path\.insert.*\n', '', test_content)

        # Remove vitest imports if present (we use Node assert now)
        test_content = re.sub(r"import \{[^}]*\} from ['\"]vitest['\"]\s*;?\n?", '', test_content)

        if has_assert and has_src_import:
            if self.debug:
                self.log(f"  ✅ JavaScript test imports already correct", "INFO")
            return test_content

        self.log(f"  🔧 INJECTING missing JavaScript test imports (assert={not has_assert}, src_import={not has_src_import})", "WARN")

        lines = test_content.split('\n')
        injection = []

        if not has_assert:
            injection.append("import assert from 'node:assert/strict';")

        if not has_src_import:
            # Use PascalCase for JS class imports
            injection.append(f"import {{ {class_name} }} from '../src/{class_name}.js';")

        if injection:
            injection.append("")
            lines = injection + lines

        return '\n'.join(lines)

    def _ensure_test_imports_typescript(self, test_content: str, module_name: str, class_name: str) -> str:
        """TYPESCRIPT ONLY: Ensure test file (controller.node.mjs) has correct Node assert imports.

        Note: For TS widgets, tests are written in JS (controller.node.mjs) to avoid
        compilation complexity. The tests import the compiled JS or use dynamic import.
        """
        import re

        # Check for Node assert import
        has_assert = "from 'node:assert" in test_content or 'from "node:assert' in test_content
        has_src_import = f"from '../src/" in test_content or f'from "../src/' in test_content

        # Remove any Python imports that shouldn't be there
        test_content = re.sub(r'import sys\s*\n', '', test_content)
        test_content = re.sub(r'from pathlib import Path\s*\n', '', test_content)
        test_content = re.sub(r'sys\.path\.insert.*\n', '', test_content)

        # Remove vitest imports if present (we use Node assert now)
        test_content = re.sub(r"import \{[^}]*\} from ['\"]vitest['\"]\s*;?\n?", '', test_content)

        if has_assert and has_src_import:
            if self.debug:
                self.log(f"  ✅ TypeScript test imports already correct", "INFO")
            return test_content

        self.log(f"  🔧 INJECTING missing TypeScript test imports (assert={not has_assert}, src_import={not has_src_import})", "WARN")

        lines = test_content.split('\n')
        injection = []

        if not has_assert:
            injection.append("import assert from 'node:assert/strict';")

        if not has_src_import:
            # For TS, import from .js (compiled) or .ts with ts-node
            injection.append(f"import {{ {class_name} }} from '../src/{class_name}.js';")

        if injection:
            injection.append("")
            lines = injection + lines

        return '\n'.join(lines)

    def _ensure_test_imports_go(self, test_content: str, module_name: str, widget_id: str) -> str:
        """GO ONLY: Ensure test file has correct package declaration and imports."""
        # Required: package declaration and imports
        has_package = test_content.strip().startswith('package ')
        has_testing_import = '"testing"' in test_content
        module_path = f'github.com/cartographer/{widget_id}/src'
        has_widget_import = module_path in test_content

        if has_package and has_testing_import and has_widget_import:
            if self.debug:
                self.log(f"  ✅ Go test imports already correct", "INFO")
            return test_content

        self.log(f"  🔧 INJECTING missing Go test imports (package={not has_package}, testing={not has_testing_import}, widget={not has_widget_import})", "WARN")

        # Remove any Python imports that shouldn't be there
        import re
        test_content = re.sub(r'import sys\s*\n', '', test_content)
        test_content = re.sub(r'from pathlib import Path\s*\n', '', test_content)
        test_content = re.sub(r'sys\.path\.insert.*\n', '', test_content)

        lines = test_content.split('\n')
        injection = []

        if not has_package:
            package_name = module_name.replace('-', '_').replace('.', '_')
            injection.append(f"package {package_name}_test")
            injection.append("")

        if not has_testing_import or not has_widget_import:
            injection.append("import (")
            if not has_testing_import:
                injection.append('\t"testing"')
            if not has_widget_import:
                injection.append(f'\twidget "{module_path}"')
            injection.append(")")
            injection.append("")

        if injection:
            lines = injection + lines

        return '\n'.join(lines)

    def _ensure_test_imports_rust(self, test_content: str, module_name: str, crate_name: str) -> str:
        """RUST ONLY: Ensure test file has correct use statements."""
        # For integration tests, need: use crate_name::Widget;
        has_crate_import = f"use {crate_name}::" in test_content

        if has_crate_import:
            if self.debug:
                self.log(f"  ✅ Rust test imports already correct", "INFO")
            return test_content

        self.log(f"  🔧 INJECTING missing Rust test imports (crate_import={not has_crate_import})", "WARN")

        # Remove any Python imports that shouldn't be there
        import re
        test_content = re.sub(r'import sys\s*\n', '', test_content)
        test_content = re.sub(r'from pathlib import Path\s*\n', '', test_content)
        test_content = re.sub(r'sys\.path\.insert.*\n', '', test_content)

        lines = test_content.split('\n')
        injection = []

        if not has_crate_import:
            # Try to guess the main struct/type name from module_name
            # Convert snake_case to PascalCase
            parts = module_name.replace('-', '_').split('_')
            type_name = ''.join(word.capitalize() for word in parts)
            injection.append(f"use {crate_name}::{type_name};")
            injection.append("")

        if injection:
            lines = injection + lines

        return '\n'.join(lines)

    def _extract_method_signatures(self, source_code: str, class_name: str) -> str:
        """Extract __init__ and main methods from source code for reference in tests"""
        import re

        signatures = []

        # Find __init__ method
        init_match = re.search(rf'def __init__\(self, (.*?)\):', source_code, re.DOTALL)
        if init_match:
            params = init_match.group(1).replace('\n', ' ').strip()
            signatures.append(f"{class_name}.__init__(self, {params})")

        # Find other public methods (not starting with _) - handle return types
        methods = re.findall(r'def (\w+)\(self, (.*?)\)(?:\s*->\s*\w+)?:', source_code)
        for method_name, params in methods:
            if not method_name.startswith('_') and method_name != '__init__':
                params = params.replace('\n', ' ').strip()
                signatures.append(f"{class_name}.{method_name}(self, {params})")

        if signatures:
            return "\n".join(signatures)
        return ""

    def _strip_markdown_fences(self, text: str) -> str:
        """Remove markdown code fence wrappers (```json ... ```)"""
        text = text.strip()
        # Match opening fence: ```language or just ```
        if text.startswith("```"):
            # Find the end of the opening fence line
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text.strip()

    def _strip_thinking(self, text: str) -> str:
        """
        Remove thinking tags from model output AGGRESSIVELY.
        Strips tags BEFORE and INSIDE content, then extracts JSON if possible.
        """
        if not text: return ""
        
        # First strip markdown fences
        text = self._strip_markdown_fences(text)

        # STEP 1: Remove ALL thinking/reasoning blocks
        for tag in ["think", "reasoning", "thought"]:
            # Remove blocks like <think>...</think>
            text = re.sub(rf'<{tag}>.*?</{tag}>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # Remove stray tags
            text = re.sub(rf'</?{tag}.*?>', '', text, flags=re.IGNORECASE)

        # STEP 2: Find the JSON object if the context suggests JSON is expected
        # (We only do this if it looks like there's actual garbage around the JSON)
        text = text.strip()
        if text.startswith('{') or '[' in text:
            start = text.find('{')
            if start != -1:
                # Find matching closing brace
                brace_count = 0
                for i in range(start, len(text)):
                    if text[i] == '{': brace_count += 1
                    elif text[i] == '}': 
                        brace_count -= 1
                        if brace_count == 0:
                            return text[start:i+1]
        
        return text.strip()

    # ========================================================================
    # Logging
    # ========================================================================
    def log(self, message: str, level: str = "INFO"):
        """Log to file and stdout with timestamp"""
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "widget_count": self.generated_count
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        emoji = {"INFO": "📝", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️"}.get(level, "📝")
        print(f"{emoji} [{timestamp}] {message}")

    def debug_log(self, section: str, data: Dict):
        """Write detailed debug information to debug file"""
        if not self.debug:
            return

        timestamp = datetime.now().isoformat()
        separator = "=" * 80

        with open(self.debug_file, "a") as f:
            f.write(f"\n{separator}\n")
            f.write(f"[{timestamp}] {section}\n")
            f.write(f"{separator}\n\n")

            for key, value in data.items():
                f.write(f"--- {key} ---\n")
                if isinstance(value, (dict, list)):
                    f.write(json.dumps(value, indent=2))
                else:
                    f.write(str(value))
                f.write("\n\n")

            f.write("\n")

    # ========================================================================
    # Phase 1: Generate Widget Ideas
    # ========================================================================
    async def get_existing_widgets(self) -> str:
        """Get summary of existing widgets from library"""
        try:
            result = subprocess.run(
                ["cartographer", "search", ""],
                capture_output=True,
                text=True,
                timeout=10
            )
            data = json.loads(result.stdout)
            widget_ids = [w["id"] for w in data.get("library", [])]
            return f"{len(widget_ids)} widgets: " + ", ".join(widget_ids[:50])
        except Exception as e:
            self.log(f"Failed to get existing widgets: {e}", "WARN")
            return "Unable to fetch existing widgets"

    async def generate_widget_idea(self) -> Optional[Dict]:
        """Generate a single unique widget idea (FRESH CONTEXT)"""
        self.log("Generating new widget idea...")

        existing = await self.get_existing_widgets()

        system_prompt = self.brainstorm_prompt
        if self.profile.get("strip_thinking"):
            # Use NeMo's built-in thinking toggle
            system_prompt = "detailed thinking off\n\n" + system_prompt
            system_prompt += "\n\nIMPORTANT: Output ONLY the JSON object. Do NOT use thinking tags or any other text."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""Current widget library: {existing}

Propose ONE unique widget idea that doesn't duplicate existing widgets.
Return ONLY valid JSON matching the specified format. No thinking tags, no explanations, ONLY JSON."""}
        ]

        try:
            # Build chat kwargs - some params only supported by specific clients
            chat_kwargs = {
                "messages": messages,
                "temperature": self.profile["temperature_brainstorm"],
                "max_tokens": self.profile["max_tokens_brainstorm"],
                "top_p": 0.95  # Slightly more focused sampling
            }
            # Add client-specific params
            if isinstance(self.client, LlamaClient):
                chat_kwargs["repeat_penalty"] = 1.1  # Penalize repetitive thinking patterns
                chat_kwargs["response_format"] = {"type": "json_object"}
            # GrokClient doesn't need response_format for simple JSON - prompt instructs it

            response = await self.client.chat(**chat_kwargs)

            # Strip thinking tags if configured
            content = self._strip_thinking(response["content"])

            # Try to parse JSON
            try:
                spec = json.loads(content)
            except json.JSONDecodeError as json_err:
                # Log the problematic content for debugging
                self.log(f"JSON parse error. Content preview: {content[:200]}...", "WARN")
                raise Exception(f"{json_err}") from json_err

            self.log(f"Generated idea: {spec.get('widget_id', 'UNKNOWN')}")
            return spec

        except Exception as e:
            self.log(f"Failed to generate idea: {e}", "ERROR")
            return None

    # ========================================================================
    # Phase 2: Implement Widget
    # ========================================================================
    async def _generate_single_file(self, file_type: str, spec: Dict, language: str, prompt: str) -> Optional[Dict]:
        """Generate a single file using LLM (faster, more reliable). Returns full response object."""
        # Use markers for GrokClient to reliably extract JSON
        is_grok = isinstance(self.client, GrokClient)

        if is_grok:
            # For xAI/Grok, use explicit markers for reliable extraction
            system_prompt = """You are a code generation assistant. Generate clean, production-ready code.
CRITICAL: You MUST wrap your JSON response between <WIDGET_OUTPUT> and </WIDGET_OUTPUT> markers.
Always output raw code in the content field, never wrapped in ```language``` fences."""

            # Append marker example to the user prompt
            grok_suffix = """

⚠️ REQUIRED OUTPUT FORMAT - Wrap response in markers:
<WIDGET_OUTPUT>
{"content": "your code/json content here"}
</WIDGET_OUTPUT>"""
            prompt = prompt + grok_suffix
        else:
            # For local LLMs with JSON mode
            system_prompt = "You are a code generation assistant. Generate clean, production-ready code. Return ONLY valid JSON responses with no markdown wrappers. Always output raw code, never wrapped in ```language``` fences."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # Debug log the request
        if self.debug:
            self.debug_log(f"LLM REQUEST: {file_type}", {
                "file_type": file_type,
                "widget_id": spec.get('widget_id', 'unknown'),
                "language": language,
                "system_prompt": system_prompt,
                "user_prompt": prompt,
                "temperature": self.profile["temperature_code"],
                "max_tokens": 3000
            })

        try:
            chat_kwargs = {
                "messages": messages,
                "temperature": self.profile["temperature_code"],
                "max_tokens": 3000,  # Smaller per file
            }
            # Only add response_format for LlamaClient
            if isinstance(self.client, LlamaClient):
                chat_kwargs["response_format"] = {"type": "json_object"}

            response = await self.client.chat(**chat_kwargs)

            # Debug log the raw response
            if self.debug:
                self.debug_log(f"LLM RESPONSE: {file_type}", {
                    "file_type": file_type,
                    "widget_id": spec.get('widget_id', 'unknown'),
                    "raw_response": response["content"],
                    "response_length": len(response["content"])
                })

            raw_content = response.get("content", "")
            if not raw_content:
                self.log(f"  ⚠️ Empty response from LLM for {file_type}", "WARN")
                return None

            content = self._strip_thinking(raw_content)
            if not content:
                self.log(f"  ⚠️ Content empty after strip_thinking for {file_type}", "WARN")
                return None

            # For GrokClient, extract content from markers
            if is_grok:
                import re
                marker_match = re.search(r'<WIDGET_OUTPUT>\s*(.*?)\s*</WIDGET_OUTPUT>', content, re.DOTALL)
                if marker_match:
                    content = marker_match.group(1).strip()
                else:
                    # Fallback: find JSON by locating first { and matching closing }
                    first_brace = content.find('{')
                    if first_brace != -1:
                        # Find balanced closing brace
                        depth = 0
                        in_string = False
                        escape = False
                        for i, c in enumerate(content[first_brace:], first_brace):
                            if escape:
                                escape = False
                                continue
                            if c == '\\' and in_string:
                                escape = True
                                continue
                            if c == '"' and not escape:
                                in_string = not in_string
                            elif not in_string:
                                if c == '{':
                                    depth += 1
                                elif c == '}':
                                    depth -= 1
                                    if depth == 0:
                                        content = content[first_brace:i+1]
                                        break
                    else:
                        self.log(f"  ⚠️ Could not extract JSON from Grok response for {file_type}", "WARN")
                        if self.debug:
                            self.debug_log(f"EXTRACTION FAILED: {file_type}", {"raw_content": content})
                        return None

            result = json.loads(content)

            # Debug log the parsed result
            if self.debug:
                llm_filename = result.get("filename", "NOT PROVIDED")
                self.debug_log(f"PARSED RESULT: {file_type}", {
                    "file_type": file_type,
                    "widget_id": spec.get('widget_id', 'unknown'),
                    "after_strip_thinking": content,
                    "parsed_json": result,
                    "content_length": len(result.get("content", "")) if isinstance(result.get("content"), str) else 0,
                    "llm_provided_filename": llm_filename,
                    "note": "We ignore LLM filename and use calculated filename instead"
                })

            # Strip markdown code fence markers from content field if present
            if "content" in result and isinstance(result["content"], str):
                content_str = result["content"]
                # Remove markdown code fence markers (```language ... ```)
                if content_str.startswith("```"):
                    # Find the first newline after the opening fence
                    first_newline = content_str.find("\n")
                    if first_newline != -1:
                        content_str = content_str[first_newline + 1:]
                    # Remove closing fence
                    if content_str.endswith("```"):
                        content_str = content_str[:-3]
                    content_str = content_str.strip()
                result["content"] = content_str

            return result  # Return full object for flexibility

        except Exception as e:
            self.log(f"Failed to generate {file_type}: {e}", "ERROR")
            if self.debug:
                self.debug_log(f"ERROR: {file_type}", {
                    "file_type": file_type,
                    "error": str(e),
                    "exception_type": type(e).__name__
                })
            return None

    async def implement_widget_files(self, spec: Dict, language: str, is_mixed_language: bool = False) -> Optional[Dict[str, str]]:
        """
        Generate widget files ONE AT A TIME (Codex-style approach).
        Much faster and more reliable than generating all at once!

        Args:
            spec: Widget specification
            language: Implementation language
            is_mixed_language: If True, may generate multiple src files (when mixing languages)
        """
        self.log(f"Generating code for {spec['widget_id']} in {language}...")

        # Get proper file extension for this language (used in all prompts)
        file_ext = self._get_file_extension(language)

        # Calculate standard filenames upfront
        calculated_filenames = self._calculate_filenames(spec['widget_id'], language)
        self.log(f"Using standard filenames: {calculated_filenames}", "INFO")

        files = {}

        # 1. Generate widget.json (~500 tokens, ~30s)
        self.log(f"  → Generating widget.json...", "INFO")
        
        manifest_prompt = f"""You are creating a widget manifest file in Cartographer format.

WIDGET_ID: {spec['widget_id']}
WIDGET_NAME: {spec.get('widget_name', spec['widget_id'])}
LANGUAGE: {language}
DESCRIPTION: {spec.get('description', '')}

FULL SPEC: {json.dumps(spec, indent=2)}

OUTPUT FORMAT - Return ONLY this JSON structure:
{{
  "meta": {{
    "id": "{spec['widget_id']}",
    "name": "{spec.get('widget_name', spec['widget_id'])}",
    "version": "1.0.0",
    "type": "widget",
    "domain": "{spec.get('domain', 'backend')}",
    "tags": ["{spec.get('category', 'utility')}"],
    "maturity": "stable"
  }},
  "description": "{spec.get('description', 'A useful widget')}",
  "tech_stack": {{
    "language": "{language}",
    "language_version": ">=3.8",
    "dependencies": {json.dumps(spec.get('dependencies', []))}
  }},
  "integration_guide": {{
    "usage": "Import the main class and use the core methods.",
    "constraints": "No external dependencies required beyond listed tech_stack"
  }},
  "depends_on": []
}}

CRITICAL:
- Use the EXACT structure above.
- Ensure all fields in 'meta' are present.
- Output ONLY valid JSON.
"""

        widget_json = ""
        for attempt in range(2):
            widget_json_response = await self._generate_single_file(
                "widget.json",
                spec,
                language,
                manifest_prompt
            )
            
            if widget_json_response:
                # Try to extract JSON robustly
                raw_json = widget_json_response.get("content", "")
                if not raw_json and attempt == 0:
                    self.log("⚠️ widget.json content was empty, retrying...", "WARN")
                    continue
                    
                # If the model returned the JSON object directly (not inside "content" field), 
                # or if it wrapped it in "content"
                if isinstance(widget_json_response.get("content"), dict):
                    widget_json = json.dumps(widget_json_response["content"], indent=2)
                elif raw_json:
                    # Check if it's already valid JSON
                    try:
                        parsed = json.loads(raw_json)
                        widget_json = json.dumps(parsed, indent=2)
                    except:
                        # Try to extract JSON from the string
                        parsed = self._extract_json(raw_json)
                        if parsed:
                            widget_json = json.dumps(parsed, indent=2)
                        else:
                            widget_json = raw_json # Last resort
                
                if widget_json and len(widget_json) > 20:
                    break
            
            if attempt == 0: self.log("⚠️ widget.json generation failed/empty, retrying...", "WARN")

        if not widget_json:
            self.log(f"❌ Failed to generate valid widget.json", "ERROR")
            return None
            
        files["widget_json"] = widget_json
        self.log(f"  → widget.json content length: {len(widget_json)} chars", "INFO")

        # 2. Generate src file(s) (~2000 tokens, ~90s)
        self.log(f"  → Generating source code...", "INFO")

        # Special note for Rust about lib.rs
        rust_note = ""
        if language.lower() == "rust":
            rust_note = """
⚠️ CRITICAL FOR RUST:
- This will be saved as src/lib.rs (library crate entry point)
- All public items must use 'pub' keyword
- Structure as a library, not a binary
- Example: pub struct Widget { ... } pub fn new() -> Widget { ... }
"""

        src_prompt = f"""Generate implementation code for a widget.

WIDGET: {spec['widget_id']}
LANGUAGE: {language}
FILE: {calculated_filenames['src_filename']}
{rust_note}
ORIGINAL IDEA/SPEC:
{json.dumps(spec, indent=2)}

WIDGET.JSON (manifest to implement):
{files["widget_json"]}

Return ONLY this JSON structure:
{{"content": "raw source code here"}}

DO NOT include a "filename" field. The file will be saved as: {calculated_filenames['src_filename']}

Requirements:
- Implement all core_methods from spec and widget.json exactly
- Use real, importable packages (no placeholders)
- Async-first for I/O operations
- Dependency injection via constructor
- No markdown code fences
- Production-ready quality"""

        src_response = await self._generate_single_file(
            "src file",
            spec,
            language,
            src_prompt
        )
        if not src_response:
            self.log(f"❌ src_response is None", "ERROR")
            return None

        # Handle both single file and multiple files responses
        if "files" in src_response:
            # Multiple files case (when mixing languages)
            files["src_files"] = src_response.get("files", [])
            self.log(f"  → Generated {len(files['src_files'])} source files", "INFO")
        else:
            # Single file case (normal) - use calculated filename
            src_filename = calculated_filenames['src_filename']
            self.log(f"  → Using calculated src filename: {src_filename}", "INFO")

            files["src_file"] = {
                "filename": src_filename,
                "content": src_response.get("content", "")
            }
            content_len = len(files["src_file"]["content"])
            self.log(f"  → src_file content length: {content_len} chars", "INFO")

        # 3. Generate test file (~2000 tokens, ~90s)
        self.log(f"  → Generating tests...", "INFO")

        # Get comprehensive language guidelines
        language_guidelines = self._get_language_guidelines(language)

        # Get source code for context
        src_content = src_response.get("content", "") if src_response else ""

        # Extract actual class name from source code (fallback to guessing from widget_id)
        extracted_class_name = self._extract_class_name_from_source(src_content) if src_content else ""
        class_name = extracted_class_name or spec.get('class_name', spec['widget_id'].replace('-', '_').title())
        method_signatures = self._extract_method_signatures(src_content, class_name) if src_content else ""

        # Detect async methods to alert test generator
        has_async_methods = "async def" in src_content if src_content else False
        async_warning = "\n⚠️ IMPORTANT: This source code contains ASYNC methods (async def). Tests MUST use 'await' when calling these methods!" if has_async_methods else ""

        # Get the actual src filename for import instructions
        actual_src_filename = src_filename if 'src_filename' in locals() else f"{spec['widget_id']}.{file_ext}"
        src_module_name = actual_src_filename.replace(f".{file_ext}", "")

        # Build language-specific import instruction
        if language.lower() == "python":
            import_instruction = f"- Import statement MUST be: from src.{src_module_name} import {class_name}"
        elif language.lower() in ["javascript", "typescript"]:
            # Use snake_case filename (src_module_name), not PascalCase class name
            import_instruction = f"- Import statement MUST be: import {{ {class_name} }} from '../src/{src_module_name}.js'"
        elif language.lower() == "go":
            import_instruction = f'- Import using go.mod module path: widget "github.com/cartographer/{spec["widget_id"]}/src"'
        elif language.lower() == "rust":
            crate_name = spec['widget_id'].replace('-', '_').replace('.', '_')
            import_instruction = f"- Import from crate: use {crate_name}::{class_name};"
        else:
            import_instruction = f"- Import the {class_name} class from src/{actual_src_filename}"

        test_response = await self._generate_single_file(
            "test file",
            spec,
            language,
            f"""Generate tests for a widget implementation.

WIDGET: {spec['widget_id']}
LANGUAGE: {language}
FILE: {calculated_filenames['test_filename']}
CORE METHODS TO TEST: {json.dumps(spec.get('core_methods', []), indent=2)}{async_warning}

⚠️ CRITICAL IMPORT INFORMATION:
- Source file is: src/{actual_src_filename}
- Main class name: {class_name}
{import_instruction}

METHOD SIGNATURES (use exactly as shown):
{method_signatures if method_signatures else "(See source code below)"}

FULL SOURCE CODE:
{src_content}

{language_guidelines}

Return ONLY this JSON structure:
{{"content": "raw test code here"}}

DO NOT include a "filename" field. The file will be saved as: {calculated_filenames['test_filename']}

Requirements:
- FOLLOW ALL LANGUAGE GUIDELINES ABOVE EXACTLY
- Test all core methods from spec
- Use mocks for external deps
- Match method signatures EXACTLY
- Self-contained, no external calls
- No markdown code fences"""
        )
        if not test_response:
            self.log(f"❌ test_response is None", "ERROR")
            return None

        # Use calculated test filename
        test_filename = calculated_filenames['test_filename']
        self.log(f"  → Using calculated test filename: {test_filename}", "INFO")

        # Ensure test has correct imports (safety net) - language-specific
        test_content = test_response.get("content", "")
        widget_id = spec.get('widget_id', '')

        # Dispatch to language-specific import injection
        if language.lower() == "python":
            test_content = self._ensure_test_imports_python(test_content, src_module_name, class_name)
        elif language.lower() == "javascript":
            test_content = self._ensure_test_imports_javascript(test_content, src_module_name, class_name)
        elif language.lower() == "typescript":
            test_content = self._ensure_test_imports_typescript(test_content, src_module_name, class_name)
        elif language.lower() == "go":
            test_content = self._ensure_test_imports_go(test_content, src_module_name, widget_id)
        elif language.lower() == "rust":
            crate_name = widget_id.replace('-', '_').replace('.', '_')
            test_content = self._ensure_test_imports_rust(test_content, src_module_name, crate_name)

        files["test_file"] = {
            "filename": test_filename,
            "content": test_content
        }
        test_content_len = len(files["test_file"]["content"])
        self.log(f"  → test_file content length: {test_content_len} chars", "INFO")

        # For JS/TS: Also generate the Python pytest wrapper
        if language.lower() in ["javascript", "typescript"]:
            wrapper_filename = calculated_filenames.get('test_wrapper_filename')
            if wrapper_filename:
                wrapper_content = self._generate_js_test_wrapper(spec.get('widget_id', ''))
                files["test_wrapper_file"] = {
                    "filename": wrapper_filename,
                    "content": wrapper_content
                }
                self.log(f"  → Generated pytest wrapper: {wrapper_filename}", "INFO")

        # 4. Generate example (~1000 tokens, ~45s)
        self.log(f"  → Generating example...", "INFO")
        example_response = await self._generate_single_file(
            "example file",
            spec,
            language,
            f"""Generate a usage example for a widget.

WIDGET: {spec['widget_id']}
LANGUAGE: {language}
FILE: {calculated_filenames['example_filename']}

FULL SOURCE CODE (for reference):
```python
{src_content}
```

⚠️ CRITICAL IMPORT INFORMATION:
- Source file is: src/{actual_src_filename}
- Main class name: {class_name}
- Import statement MUST be: from src.{src_module_name} import {class_name}

Return ONLY this JSON structure:
{{"content": "raw example code here"}}

DO NOT include a "filename" field. The file will be saved as: {calculated_filenames['example_filename']}

Requirements:
- Show basic instantiation using the class constructor from source code
- Demonstrate typical usage (1-2 scenarios) using actual methods from source
- Import using the EXACT import statement shown above
- Runnable without external deps
- Educational and clear
- No markdown code fences"""
        )
        if not example_response:
            self.log(f"❌ example_response is None", "ERROR")
            return None

        # Use calculated example filename
        example_filename = calculated_filenames['example_filename']
        self.log(f"  → Using calculated example filename: {example_filename}", "INFO")

        files["example_file"] = {
            "filename": example_filename,
            "content": example_response.get("content", "")
        }
        example_content_len = len(files["example_file"]["content"])
        self.log(f"  → example_file content length: {example_content_len} chars", "INFO")

        self.log(f"  ✅ All files generated successfully!", "SUCCESS")
        return files

    def extract_metadata_from_code(self, language: str, src_content: str, test_content: str, example_content: str) -> Dict:
        """Extract actual metadata from generated code files to hydrate widget.json TODOs"""
        import re

        metadata = {
            "actual_dependencies": [],
            "actual_methods": [],
            "usage_description": "",
            "constraints_found": []
        }

        try:
            # Extract imports/dependencies
            if language == "python":
                imports = re.findall(r'^(?:from|import)\s+(\S+)', src_content, re.MULTILINE)
                metadata["actual_dependencies"] = list(set([imp.split('.')[0] for imp in imports if not imp.startswith('.')]))

                # Extract class/function definitions
                methods = re.findall(r'def\s+(\w+)\s*\(', src_content)
                metadata["actual_methods"] = [m for m in methods if not m.startswith('_')]

            elif language in ["typescript", "javascript"]:
                imports = re.findall(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", src_content)
                metadata["actual_dependencies"] = [imp for imp in imports if not imp.startswith('.')]

                # Extract method/function names
                methods = re.findall(r'(?:function|async function|\w+\s*\(|\.(\w+)\s*=\s*(?:function|async|.*=>))', src_content)
                metadata["actual_methods"] = list(set([m for m in methods if m and not m.startswith('_')]))

            elif language == "go":
                imports = re.findall(r'import\s+["\']([^"\']+)["\']', src_content)
                metadata["actual_dependencies"] = imports

                methods = re.findall(r'func\s+\(.*?\)\s+(\w+)\s*\(', src_content)
                metadata["actual_methods"] = methods

            elif language == "rust":
                imports = re.findall(r'use\s+([^;]+);', src_content)
                metadata["actual_dependencies"] = imports

                methods = re.findall(r'pub\s+fn\s+(\w+)\s*\(', src_content)
                metadata["actual_methods"] = methods

            # Extract usage from example
            if example_content:
                first_lines = '\n'.join(example_content.split('\n')[:10])
                metadata["usage_description"] = f"See examples/ for typical usage patterns"

            # Check for constraints in comments
            if "TODO" in src_content or "FIXME" in src_content:
                metadata["constraints_found"].append("Some TODOs remain in implementation")

            self.log(f"Extracted: {len(metadata['actual_methods'])} methods, {len(metadata['actual_dependencies'])} dependencies", "INFO")
            return metadata

        except Exception as e:
            self.log(f"Error extracting metadata: {e}", "WARN")
            return metadata

    def hydrate_widget_json(self, widget_json_str: str, spec: Dict, language: str,
                           src_content: str, test_content: str, example_content: str) -> str:
        """Fill TODOs in widget.json by inspecting actual generated code"""
        try:
            widget_data = json.loads(widget_json_str)
            metadata = self.extract_metadata_from_code(language, src_content, test_content, example_content)

            self.log(f"Hydrating widget.json with actual implementation details...", "INFO")

            # Fill description TODO
            if "[TODO" in widget_data.get("description", ""):
                widget_data["description"] = spec.get("description", widget_data["description"])

            # Fill tech_stack
            if "tech_stack" in widget_data:
                widget_data["tech_stack"]["language"] = language
                if metadata["actual_dependencies"]:
                    widget_data["tech_stack"]["dependencies"] = metadata["actual_dependencies"]

            # Fill integration_guide
            if "integration_guide" in widget_data:
                if "[TODO" in widget_data["integration_guide"].get("usage", ""):
                    usage = f"Import the main class from src/ and instantiate with appropriate parameters. "
                    if metadata["actual_methods"]:
                        usage += f"Available methods: {', '.join(metadata['actual_methods'][:3])}. See examples/ for complete usage."
                    widget_data["integration_guide"]["usage"] = usage

                if "[TODO" in widget_data["integration_guide"].get("constraints", ""):
                    constraints = spec.get("constraints", "No external dependencies required beyond listed tech_stack.")
                    if metadata["constraints_found"]:
                        constraints = "; ".join(metadata["constraints_found"])
                    widget_data["integration_guide"]["constraints"] = constraints

            # Update spec methods if needed
            if spec.get("core_methods") and "core_methods" not in widget_data:
                widget_data["core_methods"] = spec.get("core_methods", [])

            self.log(f"✅ widget.json hydrated successfully", "SUCCESS")
            return json.dumps(widget_data, indent=2)

        except Exception as e:
            self.log(f"Failed to hydrate widget.json: {e}", "WARN")
            return widget_json_str

    def write_widget_files(self, widget_id: str, files: Dict, language: str = "python", spec: Dict = None) -> Path:
        """Write generated files to checkout directory using ONLY calculated filenames

        Args:
            widget_id: Widget ID (e.g., 'logic-api-key-rotator')
            files: Generated file contents
            language: Target language
            spec: Original widget spec (optional)
        """
        # Use language subdirectory structure: checkouts/{language}/{widget_id}/
        checkout_dir = Path.cwd() / "checkouts" / language / widget_id

        # Calculate the ACTUAL filenames we will use (LLM has no control over this)
        # No need to strip suffix - widget_id is already clean
        calculated_filenames = self._calculate_filenames(widget_id, language)

        self.log(f"Writing files to {checkout_dir}", "INFO")
        self.log(f"Using calculated filenames: {calculated_filenames}", "INFO")

        # Debug log what we're about to write
        if self.debug:
            debug_data = {"widget_id": widget_id, "checkout_dir": str(checkout_dir)}
            debug_data["calculated_filenames"] = calculated_filenames
            for key, value in files.items():
                if isinstance(value, dict) and "content" in value:
                    llm_filename = value.get("filename", "NO FILENAME")
                    debug_data[f"{key}_llm_filename"] = llm_filename
                    debug_data[f"{key}_length"] = len(value.get("content", ""))
                    debug_data[f"{key}_content_empty"] = len(value.get("content", "")) == 0
                    debug_data[f"{key}_preview"] = value.get("content", "")[:500]
                elif isinstance(value, str):
                    debug_data[f"{key}_length"] = len(value)
                    debug_data[f"{key}_preview"] = value[:500]
            self.debug_log("WRITING FILES", debug_data)

        # Ensure checkout directory exists
        if not checkout_dir.exists():
            self.log(f"ERROR: Checkout directory does not exist: {checkout_dir}", "ERROR")
            return checkout_dir

        # Write widget.json
        if "widget_json" in files:
            widget_json_path = checkout_dir / "widget.json"
            widget_json_path.write_text(files["widget_json"])
            self.log(f"✓ Wrote widget.json ({len(files['widget_json'])} bytes)", "INFO")

        # Write language-specific build files
        if language.lower() == "rust":
            # Generate and write Cargo.toml
            cargo_toml_content = self._generate_cargo_toml(widget_id, spec or {})
            cargo_toml_path = checkout_dir / "Cargo.toml"
            cargo_toml_path.write_text(cargo_toml_content)
            self.log(f"✓ Wrote Cargo.toml ({len(cargo_toml_content)} bytes)", "INFO")

            # Rust expects src/lib.rs instead of src/{module_name}.rs for library crates
            # We need to ensure the src file is named lib.rs
            if "src_file" in files:
                src_dir = checkout_dir / "src"
                src_dir.mkdir(exist_ok=True, parents=True)

                # Always write as lib.rs for Rust library crates
                src_path = src_dir / "lib.rs"
                content_len = len(files["src_file"]["content"])
                src_path.write_text(files["src_file"]["content"])
                self.log(f"✓ Wrote src/lib.rs ({content_len} bytes)", "INFO")

        elif language.lower() == "go":
            # Generate and write go.mod
            go_mod_content = self._generate_go_mod(widget_id, spec or {})
            go_mod_path = checkout_dir / "go.mod"
            go_mod_path.write_text(go_mod_content)
            self.log(f"✓ Wrote go.mod ({len(go_mod_content)} bytes)", "INFO")

        # Write src file(s) - IGNORE LLM FILENAME, use calculated
        # (Skip for Rust since we already wrote it as lib.rs above)
        if "src_file" in files and language.lower() != "rust":
            src_dir = checkout_dir / "src"
            src_dir.mkdir(exist_ok=True, parents=True)

            # USE CALCULATED FILENAME - ignore whatever LLM provided
            filename = calculated_filenames['src_filename']

            src_path = src_dir / filename
            content_len = len(files["src_file"]["content"])
            src_path.write_text(files["src_file"]["content"])
            self.log(f"✓ Wrote src/{filename} ({content_len} bytes)", "INFO")

        if "src_files" in files:
            src_dir = checkout_dir / "src"
            src_dir.mkdir(exist_ok=True, parents=True)
            # Write multiple source files (mixed language mode)
            for idx, src_file in enumerate(files["src_files"]):
                # For multiple files, use LLM filenames (mixed language scenario)
                filename = src_file.get("filename", f"module_{idx}.py")
                if filename.startswith("src/"):
                    filename = filename[4:]
                src_path = src_dir / filename
                content_len = len(src_file.get("content", ""))
                src_path.write_text(src_file.get("content", ""))
                self.log(f"✓ Wrote src/{filename} ({content_len} bytes)", "INFO")

        # Write test file - IGNORE LLM FILENAME, use calculated
        if "test_file" in files:
            tests_dir = checkout_dir / "tests"
            tests_dir.mkdir(exist_ok=True, parents=True)

            # USE CALCULATED FILENAME - ignore whatever LLM provided
            filename = calculated_filenames['test_filename']

            test_path = tests_dir / filename
            content_len = len(files["test_file"]["content"])
            test_path.write_text(files["test_file"]["content"])
            self.log(f"✓ Wrote tests/{filename} ({content_len} bytes)", "INFO")

        # Write test wrapper file for JS/TS (Python pytest wrapper)
        if "test_wrapper_file" in files:
            tests_dir = checkout_dir / "tests"
            tests_dir.mkdir(exist_ok=True, parents=True)

            wrapper_filename = calculated_filenames.get('test_wrapper_filename', 'test_wrapper.py')
            wrapper_path = tests_dir / wrapper_filename
            content_len = len(files["test_wrapper_file"]["content"])
            wrapper_path.write_text(files["test_wrapper_file"]["content"])
            self.log(f"✓ Wrote tests/{wrapper_filename} ({content_len} bytes)", "INFO")

        # Write example file - IGNORE LLM FILENAME, use calculated
        if "example_file" in files:
            examples_dir = checkout_dir / "examples"
            examples_dir.mkdir(exist_ok=True, parents=True)

            # USE CALCULATED FILENAME - ignore whatever LLM provided
            filename = calculated_filenames['example_filename']

            example_path = examples_dir / filename
            content_len = len(files["example_file"]["content"])
            example_path.write_text(files["example_file"]["content"])
            self.log(f"✓ Wrote examples/{filename} ({content_len} bytes)", "INFO")

        self.log(f"All files written to {checkout_dir}", "SUCCESS")
        return checkout_dir

    def run_cartographer_command(self, cmd: List[str], timeout: int = 120, working_dir: Optional[Path] = None) -> tuple[bool, str]:
        """Execute cartographer command and return success, output"""
        cwd = str(working_dir) if working_dir else str(Path.cwd())
        
        # Determine script path
        script_path = str(Path(__file__).parent / "cartographer.py")
        
        # Replace 'cartographer' with 'python cartographer.py' for reliability
        if cmd[0] == "cartographer":
            cmd = [sys.executable, script_path] + cmd[1:]

        if self.debug:
            self.debug_log("COMMAND EXECUTION", {
                "command": " ".join(cmd),
                "working_directory": cwd,
                "timeout": timeout
            })

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _extract_error_context(self, content: str, error_msg: str, buffer_lines: int = 5) -> Optional[Dict]:
        """Extract error location and surrounding context for targeted fixing"""
        import re

        # Try to extract line number from error message
        line_match = re.search(r'line (\d+)', error_msg)
        if not line_match:
            return None

        error_line = int(line_match.group(1))
        lines = content.split('\n')

        if error_line > len(lines):
            return None

        # Get context window
        start_line = max(0, error_line - buffer_lines - 1)
        end_line = min(len(lines), error_line + buffer_lines)

        context_lines = lines[start_line:end_line]

        return {
            "error_line": error_line,
            "start_line": start_line + 1,  # 1-indexed for display
            "end_line": end_line,
            "context": '\n'.join(context_lines),
            "full_content": content
        }

    async def _apply_corrected_content_with_difflib(
        self,
        original_content: str,
        corrected_prompt: str,
        max_attempts: int = 3,
        validate_fn = None,
        file_type: str = "file"
    ) -> Optional[tuple[str, int]]:
        """
        Generic corrected + difflib error recovery for any file type.

        Args:
            original_content: The original file content
            corrected_prompt: Prompt asking LLM to provide corrected content
            max_attempts: Number of retry attempts
            validate_fn: Optional function to validate corrected content (e.g., json.loads for JSON)
            file_type: Description of file being fixed (for logging)

        Returns:
            Tuple of (fixed_content, changes_count) or None if all attempts fail
        """
        self.log(f"🔧 Attempting to fix {file_type} using LLM-guided corrections", "INFO")

        for attempt in range(1, max_attempts + 1):
            self.log(f"  Attempt {attempt}/{max_attempts} - Asking LLM for corrected {file_type}...", "INFO")

            try:
                # Ask model for corrected content
                response = await self.client.chat(
                    messages=[{"role": "user", "content": corrected_prompt}],
                    temperature=self.profile.get("temperature_fix", 0.5),
                    max_tokens=4000,
                )

                raw_response = response["content"].strip()
                self.log(f"  📥 Received response ({len(raw_response)} chars)", "INFO")

                # Extract content from <CORRECTED_CODE> wrapper
                content = raw_response
                if "<CORRECTED_CODE>" in raw_response and "</CORRECTED_CODE>" in raw_response:
                    start = raw_response.find("<CORRECTED_CODE>") + len("<CORRECTED_CODE>")
                    end = raw_response.find("</CORRECTED_CODE>")
                    content = raw_response[start:end].strip()
                    self.log(f"  ✂️  Extracted code from wrapper ({len(content)} chars)", "INFO")
                else:
                    # Fallback: Extract content from markdown fences if present
                    if "```" in content and content.count('```') >= 2:
                        self.log(f"  ⚠️  No <CORRECTED_CODE> wrapper found, trying markdown fences", "WARN")
                        parts = content.split('```')
                        for part in parts:
                            part_stripped = part.strip()
                            # Remove language identifier if present
                            for lang in ['python', 'json', 'javascript', 'typescript', 'java', 'go', 'rust']:
                                if part_stripped.startswith(lang):
                                    part_stripped = part_stripped[len(lang):].strip()
                                    break
                            # Check if this looks like actual content (not explanation text)
                            if len(part_stripped) > 20 and ('\n' in part_stripped or '{' in part_stripped or 'def ' in part_stripped or 'class ' in part_stripped):
                                content = part_stripped
                                self.log(f"  ✂️  Extracted from markdown fence ({len(content)} chars)", "INFO")
                                break
                    else:
                        self.log(f"  ⚠️  No wrapper or markdown fences found, using raw response", "WARN")

                content = content.strip()

                # Validate if validator provided
                if validate_fn:
                    try:
                        validate_fn(content)
                    except Exception as e:
                        self.log(f"Attempt {attempt}: Validation failed: {e}", "WARN")
                        if attempt == max_attempts:
                            return None
                        continue

                # Apply difflib-based changes
                orig_lines = original_content.split('\n')
                fixed_lines = content.split('\n')

                # If line count differs significantly, use corrected content directly
                if len(orig_lines) != len(fixed_lines):
                    changes_count = abs(len(fixed_lines) - len(orig_lines))
                    self.log(f"  🔄 Full file replacement (line count changed: {len(orig_lines)} → {len(fixed_lines)})", "INFO")
                    return (content, changes_count)

                # Same line count: use difflib to identify specific changes
                self.log(f"  🔍 Analyzing line-by-line changes using difflib...", "INFO")
                diff_lines = list(unified_diff(orig_lines, fixed_lines, lineterm='', n=0))

                # Parse diff to extract line changes
                changes = []  # (1-indexed line number, new content)

                i = 0
                while i < len(diff_lines):
                    line = diff_lines[i]

                    if line.startswith('@@'):
                        match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)', line)
                        if match:
                            line_num = int(match.group(1))

                            i += 1
                            while i < len(diff_lines) and not diff_lines[i].startswith('@@'):
                                if diff_lines[i].startswith('+'):
                                    new_content = diff_lines[i][1:]
                                    changes.append((line_num, new_content))
                                    line_num += 1
                                elif diff_lines[i].startswith('-'):
                                    pass
                                else:
                                    line_num += 1
                                i += 1
                            i -= 1
                    i += 1

                # Apply changes bottom-to-top to avoid line shifting
                if changes:
                    self.log(f"  ✏️  Applying {len(changes)} line changes to {file_type}...", "INFO")
                    work_lines = orig_lines.copy()
                    for line_num, new_content in sorted(changes, key=lambda x: x[0], reverse=True):
                        idx = line_num - 1
                        if 0 <= idx < len(work_lines):
                            work_lines[idx] = new_content
                            self.log(f"     Line {line_num}: Changed", "INFO")

                    fixed_content = '\n'.join(work_lines)
                    changes_count = len(changes)
                else:
                    self.log(f"  ℹ️  No changes detected (files are identical)", "INFO")
                    fixed_content = content
                    changes_count = 0

                # Final validation if validator provided
                if validate_fn:
                    try:
                        validate_fn(fixed_content)
                    except Exception as e:
                        self.log(f"Attempt {attempt}: Fixed content validation failed: {e}", "WARN")
                        if attempt == max_attempts:
                            return None
                        continue

                if changes_count > 0:
                    self.log(f"  ✅ Successfully fixed {file_type} on attempt {attempt} ({changes_count} changes)", "SUCCESS")
                else:
                    self.log(f"  ✅ {file_type} validated successfully (no changes needed)", "SUCCESS")
                return (fixed_content, changes_count)

            except Exception as e:
                self.log(f"Attempt {attempt}: Correction failed: {e}", "WARN")
                if attempt == max_attempts:
                    return None

        return None

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract the first valid JSON object from text, handling thinking tags and garbage."""
        if not text:
            return None
            
        # Strip thinking tags first
        text = self._strip_thinking(text)
        
        # Try to find the JSON block
        start = text.find('{')
        if start == -1:
            return None
            
        # Find the matching closing brace
        brace_count = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        # If simple extraction fails, try a more aggressive approach 
                        # (e.g. cleaning common LLM artifacts)
                        cleaned = text[start:i+1].replace('\\n', '\n').replace('\\"', '"')
                        try:
                            return json.loads(cleaned)
                        except:
                            return None
        return None

    async def fix_validation_errors_holistic(
        self,
        spec: Dict,
        language: str,
        current_files: Dict,
        validation_output: str
    ) -> Optional[Dict]:
        """Holistic approach: Give LLM full widget context and let it decide what to fix.

        Uses TAG-BASED file replacement to avoid JSON escaping hell for large code blocks.
        """
        self.log(f"🔍 Analyzing validation error with full widget context...")
        
        # Get filenames for context
        widget_id = spec.get('widget_id', 'widget')
        calculated_filenames = self._calculate_filenames(widget_id, language)

        src_filename = calculated_filenames['src_filename']
        test_filename = calculated_filenames['test_filename']
        example_filename = calculated_filenames['example_filename']

        # Extract file contents
        src_content = current_files.get("src_file", {}).get("content", "") or "".join(
            f.get("content", "") for f in current_files.get("src_files", [])
        )
        test_content = current_files.get("test_file", {}).get("content", "")
        example_content = current_files.get("example_file", {}).get("content", "")
        widget_json = current_files.get("widget_json", "{}")

        # Get build files if they exist
        cargo_toml = ""
        go_mod = ""
        if language.lower() == "rust":
            cargo_path = Path.cwd() / "checkouts" / language / widget_id / "Cargo.toml"
            if cargo_path.exists(): cargo_toml = cargo_path.read_text()
        elif language.lower() == "go":
            gomod_path = Path.cwd() / "checkouts" / language / widget_id / "go.mod"
            if gomod_path.exists(): go_mod = gomod_path.read_text()

        # Build holistic prompt
        prompt = f"""You are a debugging expert fixing validation errors in a {language} widget.

VALIDATION ERROR OUTPUT:
```
{validation_output}
```

CURRENT WIDGET FILES:

=== widget.json ===
```json
{widget_json}
```

=== src/{src_filename} ===
```{language}
{src_content}
```

=== tests/{test_filename} ===
```{language}
{test_content}
```

=== examples/{example_filename} ===
```{language}
{example_content}
```
"""
        if cargo_toml: prompt += f"\n=== Cargo.toml ===\n```toml\n{cargo_toml}\n```"
        if go_mod: prompt += f"\n=== go.mod ===\n```go\n{go_mod}\n```"

        prompt += f"""
TASK:
1. Analyze the validation error carefully.
2. Identify ALL issues (logic bugs, missing imports, manifest schema errors, etc.)
3. Provide a JSON analysis followed by the FULL corrected content for each file using tags.

CRITICAL RULES:
- If a file needs changes, you MUST provide the ENTIRE file content.
- Use the following format for each file:
<FIX_FILE path="FILE_KEY">
YOUR CORRECTED CODE HERE
</FIX_FILE>

Valid FILE_KEY values: "src_file", "test_file", "example_file", "widget_json", "cargo_toml", "go_mod"

Return your analysis as a JSON block first, then the file tags.

Example Response:
{{
  "analysis": "Root cause explanation..."
}}
<FIX_FILE path="src_file">
... full code ...
</FIX_FILE>
"""

        self.log(f"  → Calling LLM with {len(prompt)} char prompt...", "INFO")

        try:
            response = await self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=12000 # Large for multiple files
            )

            if not response or not response.get("content"):
                self.log("❌ LLM returned empty response", "ERROR")
                return None

            raw_content = response["content"]
            
            # 1. Parse JSON analysis
            analysis_data = self._extract_json(raw_content)
            if analysis_data:
                self.log(f"📋 Analysis: {analysis_data.get('analysis', 'N/A')}", "INFO")
            else:
                self.log("⚠️  Could not parse JSON analysis from response", "WARN")

            # 2. Extract files using regex tags
            import re
            fixed_files = current_files.copy()
            total_changes = 0
            
            # Non-greedy match for content between tags
            file_pattern = re.compile(r'<FIX_FILE path=["\'](.*?)["\']>(.*?)</FIX_FILE>', re.DOTALL)
            matches = file_pattern.findall(raw_content)
            
            for file_key, new_content in matches:
                new_content = new_content.strip()
                # Clean up potential markdown fences the model might have put inside the tags
                if new_content.startswith("```"):
                    lines = new_content.splitlines()
                    if len(lines) > 2:
                        new_content = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])
                
                # Normalize key
                file_key = file_key.strip().lower()
                self.log(f"🔧 Applying fix for {file_key} ({len(new_content)} chars)", "INFO")
                
                if file_key == "widget_json":
                    fixed_files["widget_json"] = new_content
                elif file_key in ["src_file", "test_file", "example_file"]:
                    if file_key in fixed_files and isinstance(fixed_files[file_key], dict):
                        fixed_files[file_key]["content"] = new_content
                    else:
                        fixed_files[file_key] = {"content": new_content, "filename": "unknown"}
                elif file_key == "cargo_toml":
                    cargo_path = Path.cwd() / "checkouts" / language / widget_id / "Cargo.toml"
                    if cargo_path.exists(): cargo_path.write_text(new_content)
                    self.log(f"  ✅ Updated Cargo.toml on disk", "INFO")
                elif file_key == "go_mod":
                    gomod_path = Path.cwd() / "checkouts" / language / widget_id / "go.mod"
                    if gomod_path.exists(): gomod_path.write_text(new_content)
                    self.log(f"  ✅ Updated go.mod on disk", "INFO")
                
                total_changes += 1

            if total_changes > 0:
                self.log(f"✅ Total files updated: {total_changes}", "SUCCESS")
                return fixed_files
            else:
                self.log("⚠️  No <FIX_FILE> tags found in response", "WARN")
                # Fallback: check if the model just returned raw JSON (old style)
                if analysis_data and "files_to_fix" in analysis_data:
                    self.log("🔄 Fallback: LLM used old JSON format for files", "INFO")
                    # Process as before... (but the JSON format is what was breaking, so maybe just fail)
                return None

        except Exception as e:
            self.log(f"❌ Error in holistic fix: {e}", "ERROR")
            import traceback
            if self.debug: self.log(traceback.format_exc(), "DEBUG")
            return None


    async def fix_validation_errors(
        self,
        spec: Dict,
        language: str,
        current_files: Dict,
        validation_output: str
    ) -> Optional[Dict]:
        """Ask LLM to fix validation errors using corrected + difflib approach for all file types.

        Uses targeted search-and-replace corrections instead of regenerating entire files.
        """
        self.log(f"Asking LLM to fix validation errors...")

        # Get proper file extension for this language
        file_ext = self._get_file_extension(language)

        # Identify which file is likely causing the error
        file_to_fix = "widget_json"  # Default

        # Smart detection: distinguish test code errors from src implementation errors
        validation_lower = validation_output.lower()

        # Test code errors (syntax, imports in test file)
        # BUT: Check if error traceback points to src/ file (import error during src module load)
        if ("importerror" in validation_lower and "test_" in validation_output) or \
           ("syntaxerror" in validation_lower and "test_" in validation_output) or \
           ("cannot import" in validation_lower and "test" in validation_lower) or \
           "pytest collection error" in validation_lower or \
           "fixture" in validation_lower:
            # Check if the actual error is in src file (import chain issue)
            if "/src/" in validation_output or "src/" in validation_output or f"src{os.sep}" in validation_output:
                # Error is actually in src file during import
                file_to_fix = "src_file"
            else:
                file_to_fix = "test_file"

        # Assertion failures - could be src OR test, but likely src logic issue
        elif "assertionerror" in validation_lower or \
             "test failed" in validation_lower or \
             "assert" in validation_lower:
            # For assertion failures, try to fix src first (implementation bug)
            # Tests are usually correct about what they expect
            file_to_fix = "src_file"
            self.log("Detected assertion failure - assuming src implementation issue", "INFO")

        # Widget.json errors
        elif "JSON" in validation_output or "Unterminated string" in validation_output or "Expecting" in validation_output:
            file_to_fix = "widget_json"

        # Src code errors (imports, syntax in src)
        # Check if error is specifically in src file (not test file)
        elif ("import" in validation_lower or "module" in validation_lower or "syntax" in validation_lower) and \
             ("/src/" in validation_output or "\\src\\" in validation_output or "src/" in validation_output or \
              "in src." in validation_lower or f".{file_ext}:" in validation_output):
            # Additional check: make sure it's not a test file error
            if not ("test_" in validation_output and "File:" in validation_output and "test_" in validation_output.split("File:")[-1].split("\n")[0]):
                file_to_fix = "src_file"

        # Example errors
        elif "example" in validation_lower or "usage" in validation_lower:
            file_to_fix = "example_file"

        # Fallback: if "test" mentioned but no clear category
        elif "test" in validation_lower:
            file_to_fix = "test_file"

        self.log(f"🎯 Target file to fix: {file_to_fix}", "INFO")

        # Debug validation output
        if not validation_output or len(validation_output.strip()) < 10:
            self.log(f"⚠️  WARNING: Validation output is empty or too short ({len(validation_output)} chars)", "WARN")
            self.log(f"  Raw validation output repr: {repr(validation_output)}", "WARN")

        self.log(f"📋 Full validation error output ({len(validation_output)} chars):", "INFO")
        self.log(validation_output, "INFO")

        # Widget.json: Use JSON validation
        if file_to_fix == "widget_json":
            widget_json = current_files.get("widget_json", "")
            if not widget_json:
                self.log("widget_json not found in current_files", "ERROR")
                return None

            # Get source code for context
            src_data = current_files.get("src_file", {})
            src_content = src_data.get("content", "") if isinstance(src_data, dict) else ""

            prompt = f"""This JSON has a syntax error. Fix it.

BROKEN JSON:
```
{widget_json}
```

ORIGINAL IDEA/SPEC (for reference):
{json.dumps(spec, indent=2)}

SOURCE CODE (for reference on actual methods/dependencies):
```python
{src_content}
```

FULL VALIDATION ERROR OUTPUT:
{validation_output}

IMPORTANT: You may explain what you're fixing, but wrap the actual corrected JSON inside these tags:
<CORRECTED_CODE>
corrected JSON here
</CORRECTED_CODE>

Any commentary outside the tags will be ignored. Only the content between <CORRECTED_CODE> tags will be used."""

            result = await self._apply_corrected_content_with_difflib(
                widget_json,
                prompt,
                max_attempts=3,
                validate_fn=json.loads,  # JSON validator
                file_type="widget.json"
            )

            if result:
                fixed_content, changes_count = result
                current_files["widget_json"] = fixed_content
                return current_files
            else:
                self.log("Failed to fix widget.json with corrected + difflib", "ERROR")
                return None

        # Test file: Use corrected + difflib with Python/test-specific validation
        elif file_to_fix == "test_file":
            test_data = current_files.get("test_file", {})
            test_content = test_data.get("content", "") if isinstance(test_data, dict) else test_data

            if not test_content:
                self.log("test_file not found in current_files", "ERROR")
                return None

            # Get full source code and filename info
            src_data = current_files.get("src_file", {})
            src_content = src_data.get("content", "") if isinstance(src_data, dict) else ""
            src_filename = src_data.get("filename", f"{spec['widget_id']}.{file_ext}") if isinstance(src_data, dict) else f"{spec['widget_id']}.{file_ext}"

            # Extract actual class name from source
            class_name = self._extract_class_name_from_source(src_content) if src_content else spec['widget_id'].replace('-', '_').title()
            src_module_name = src_filename.replace(f".{file_ext}", "")

            has_async = "async def" in src_content
            async_note = "\n⚠️ CRITICAL: Source has ASYNC methods. Tests MUST use @pytest.mark.asyncio decorator!" if has_async else ""

            # Detect async cleanup issues
            async_cleanup_issue = (
                "Event loop is closed" in validation_output or
                "Task was destroyed but it is pending" in validation_output or
                "Exception ignored while closing generator" in validation_output
            )

            # Detect Jest/Vitest syntax mismatch (JS/TS only)
            jest_vitest_issue = (
                language.lower() in ["javascript", "typescript"] and (
                    "jest.mock" in test_content or
                    "jest.fn" in test_content or
                    ("Failed to parse source" in validation_output and "invalid JS syntax" in validation_output)
                )
            )

            jest_vitest_guidance = ""
            if jest_vitest_issue:
                self.log("🔴 JEST/VITEST SYNTAX MISMATCH - Using jest.* but Vitest is running", "WARN")
                jest_vitest_guidance = """

⚠️⚠️⚠️ JEST/VITEST SYNTAX MISMATCH DETECTED ⚠️⚠️⚠️

The test uses Jest syntax (jest.mock, jest.fn) but we run tests with VITEST.

REQUIRED FIX:
1. Replace ALL jest.* with vi.* syntax
2. Add import: import { describe, it, expect, vi } from 'vitest'

REPLACEMENTS:
- jest.mock() → vi.mock()
- jest.fn() → vi.fn()
- jest.spyOn() → vi.spyOn()
- jest.resetAllMocks() → vi.resetAllMocks()

EXAMPLE:
```javascript
// ❌ WRONG (Jest syntax):
jest.mock('bull', () => ({
  default: jest.fn(() => ({
    pause: jest.fn()
  }))
}))

// ✅ CORRECT (Vitest syntax):
import { vi } from 'vitest'

vi.mock('bull', () => ({
  default: vi.fn(() => ({
    pause: vi.fn()
  }))
}))
```

This is NOT optional - we use Vitest, not Jest.
"""

            async_cleanup_guidance = ""
            if async_cleanup_issue:
                self.log("🔴 ASYNC CLEANUP ISSUE DETECTED - Event loop closed with pending tasks", "WARN")
                async_cleanup_guidance = """

⚠️⚠️⚠️ CRITICAL ASYNC CLEANUP ISSUE DETECTED ⚠️⚠️⚠️

The test is leaving async tasks running after completion, causing "Event loop is closed" errors.

REQUIRED FIX:
1. Find methods that start background tasks (start(), run(), etc.)
2. Find corresponding cleanup methods (stop(), close(), shutdown(), etc.)
3. ALWAYS call cleanup in a try/finally block:

EXAMPLE PATTERN:
```python
@pytest.mark.asyncio
async def test_something():
    queue = AsyncTaskQueue()
    await queue.start()  # Starts background tasks

    try:
        # Your test code here
        assert something
    finally:
        await queue.stop()  # CRITICAL: Always cleanup!
        # Wait for tasks to finish
        await asyncio.sleep(0.1)
```

4. If there's no stop() method, check for:
   - close()
   - shutdown()
   - cleanup()
   - Or cancel background tasks manually

5. Use try/finally to ensure cleanup happens even if test fails
6. Add small await asyncio.sleep(0.1) after cleanup to let event loop finish

This is NOT optional - async cleanup is MANDATORY for all async tests.
"""

            # Get language guidelines for context
            language_guidelines = self._get_language_guidelines(language)

            prompt = f"""Fix this test file to resolve validation errors.

CURRENT TEST FILE:
```python
{test_content}
```

FULL SOURCE CODE (for reference):
```python
{src_content}
```

⚠️ CRITICAL IMPORT INFORMATION:
- Source file is: src/{src_filename}
- Main class name: {class_name}
- Correct import: from src.{src_module_name} import {class_name}

{language_guidelines}

FULL VALIDATION ERROR OUTPUT:
{validation_output}{async_note}{jest_vitest_guidance}{async_cleanup_guidance}

COMMON FIXES:
- For ModuleNotFoundError "No module named 'src'": Add the mandatory sys.path setup at the very top
- For async tests: Add @pytest.mark.asyncio decorator to test functions
- For async fixtures: Add BOTH @pytest.fixture AND @pytest.fixture(scope="function") decorator, DO NOT make the fixture function itself async
- If you see "requested an async fixture with no plugin that handled it": The fixture should NOT be async, only the test function should be async
- Fix import paths - MUST use: from src.{src_module_name} import {class_name}
- Remove await from sync functions
- Fix pytest syntax errors
- Test the actual methods that exist in the source code

IMPORTANT: You may explain what you're fixing, but wrap the actual corrected test code inside these tags:
<CORRECTED_CODE>
corrected test code here
</CORRECTED_CODE>

Any commentary outside the tags will be ignored. Only the content between <CORRECTED_CODE> tags will be used."""

            result = await self._apply_corrected_content_with_difflib(
                test_content,
                prompt,
                max_attempts=3,
                validate_fn=None,  # No syntax validator for Python
                file_type=f"test file ({src_filename})"
            )

            if result:
                fixed_content, changes_count = result

                # Ensure imports are correct (safety net) - language-specific
                widget_id = spec.get('widget_id', '')

                # Dispatch to language-specific import injection
                if language.lower() == "python":
                    fixed_content = self._ensure_test_imports_python(fixed_content, src_module_name, class_name)
                elif language.lower() == "javascript":
                    fixed_content = self._ensure_test_imports_javascript(fixed_content, src_module_name, class_name)
                elif language.lower() == "typescript":
                    fixed_content = self._ensure_test_imports_typescript(fixed_content, src_module_name, class_name)
                elif language.lower() == "go":
                    fixed_content = self._ensure_test_imports_go(fixed_content, src_module_name, widget_id)
                elif language.lower() == "rust":
                    crate_name = widget_id.replace('-', '_').replace('.', '_')
                    fixed_content = self._ensure_test_imports_rust(fixed_content, src_module_name, crate_name)

                if isinstance(test_data, dict):
                    test_data["content"] = fixed_content
                    current_files["test_file"] = test_data
                else:
                    current_files["test_file"] = fixed_content
                return current_files
            else:
                self.log("Failed to fix test_file with corrected + difflib", "ERROR")
                return None

        # Src file: Use corrected + difflib
        elif file_to_fix == "src_file":
            src_data = current_files.get("src_file", {})
            src_content = src_data.get("content", "") if isinstance(src_data, dict) else src_data

            if not src_content:
                self.log("src_file not found in current_files", "ERROR")
                return None

            # Get widget.json and test file for context
            widget_json = current_files.get("widget_json", "")
            test_data = current_files.get("test_file", {})
            test_content = test_data.get("content", "") if isinstance(test_data, dict) else ""

            # Check if this is a test assertion failure (src logic issue)
            is_assertion_failure = "assertionerror" in validation_output.lower() or \
                                   "assert" in validation_output.lower()

            test_context = ""
            if is_assertion_failure and test_content:
                test_context = f"""

⚠️ NOTE: Tests are FAILING with assertion errors. The test expectations are likely CORRECT.
Fix the source code logic to match what the tests expect.

TEST FILE (showing what behavior is expected):
```python
{test_content}
```
"""

            prompt = f"""Fix this source file to resolve validation errors.

CURRENT SOURCE FILE:
```python
{src_content}
```

ORIGINAL IDEA/SPEC (for reference):
{json.dumps(spec, indent=2)}

WIDGET.JSON (for reference on required methods):
```json
{widget_json}
```
{test_context}
FULL VALIDATION ERROR OUTPUT:
{validation_output}

COMMON FIXES:
- Fix import statements
- Fix syntax errors
- Add missing methods (check spec and widget.json for required methods)
- Fix type annotations
- Fix undefined variables
- Ensure all core_methods from spec are implemented
- If tests are failing: fix the implementation logic to match test expectations

IMPORTANT: You may explain what you're fixing, but wrap the actual corrected source code inside these tags:
<CORRECTED_CODE>
corrected source code here
</CORRECTED_CODE>

Any commentary outside the tags will be ignored. Only the content between <CORRECTED_CODE> tags will be used."""

            result = await self._apply_corrected_content_with_difflib(
                src_content,
                prompt,
                max_attempts=3,
                validate_fn=None,
                file_type=f"source file ({spec['widget_id']})"
            )

            if result:
                fixed_content, changes_count = result
                if isinstance(src_data, dict):
                    src_data["content"] = fixed_content
                    current_files["src_file"] = src_data
                else:
                    current_files["src_file"] = fixed_content
                return current_files
            else:
                self.log("Failed to fix src_file with corrected + difflib", "ERROR")
                return None

        # Example file: Use corrected + difflib
        elif file_to_fix == "example_file":
            example_data = current_files.get("example_file", {})
            example_content = example_data.get("content", "") if isinstance(example_data, dict) else example_data

            if not example_content:
                self.log("example_file not found in current_files", "ERROR")
                return None

            # Get full source code and filename info
            src_data = current_files.get("src_file", {})
            src_content = src_data.get("content", "") if isinstance(src_data, dict) else ""
            src_filename = src_data.get("filename", f"{spec['widget_id']}.{file_ext}") if isinstance(src_data, dict) else f"{spec['widget_id']}.{file_ext}"

            # Extract actual class name from source
            class_name = self._extract_class_name_from_source(src_content) if src_content else spec['widget_id'].replace('-', '_').title()
            src_module_name = src_filename.replace(f".{file_ext}", "")

            prompt = f"""Fix this example file to resolve validation errors.

CURRENT EXAMPLE FILE:
```python
{example_content}
```

FULL SOURCE CODE (for reference):
```python
{src_content}
```

⚠️ CRITICAL IMPORT INFORMATION:
- Source file is: src/{src_filename}
- Main class name: {class_name}
- Correct import: from src.{src_module_name} import {class_name}

FULL VALIDATION ERROR OUTPUT:
{validation_output}

COMMON FIXES:
- Fix import paths - MUST use: from src.{src_module_name} import {class_name}
- Fix syntax errors
- Make code runnable
- Remove markdown fences if present
- Use actual methods from the source code

IMPORTANT: You may explain what you're fixing, but wrap the actual corrected example code inside these tags:
<CORRECTED_CODE>
corrected example code here
</CORRECTED_CODE>

Any commentary outside the tags will be ignored. Only the content between <CORRECTED_CODE> tags will be used."""

            result = await self._apply_corrected_content_with_difflib(
                example_content,
                prompt,
                max_attempts=3,
                validate_fn=None,
                file_type="example file"
            )

            if result:
                fixed_content, changes_count = result
                if isinstance(example_data, dict):
                    example_data["content"] = fixed_content
                    current_files["example_file"] = example_data
                else:
                    current_files["example_file"] = fixed_content
                return current_files
            else:
                self.log("Failed to fix example_file with corrected + difflib", "ERROR")
                return None

        return None


    def _cleanup_checkout(self, widget_id: str, language: str = None) -> bool:
        """Clean up checkout directory (move to failed or delete)

        Args:
            widget_id: Widget ID
            language: Language (if provided, uses language subdirectory structure)
        """
        if language:
            checkout_dir = Path.cwd() / "checkouts" / language / widget_id
        else:
            # Fallback: try to find the widget in any language directory
            checkouts_base = Path.cwd() / "checkouts"
            for lang_dir in checkouts_base.iterdir():
                if lang_dir.is_dir():
                    potential_dir = lang_dir / widget_id
                    if potential_dir.exists():
                        checkout_dir = potential_dir
                        break
            else:
                # Old-style flat structure
                checkout_dir = Path.cwd() / "checkouts" / widget_id

        if not checkout_dir.exists():
            return True

        try:
            # Move to failed directory for analysis
            FAILED_DIR.mkdir(exist_ok=True, parents=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            failed_path = FAILED_DIR / f"{widget_id}_{timestamp}"

            import shutil
            shutil.move(str(checkout_dir), str(failed_path))
            self.log(f"Moved failed widget to: {failed_path}", "INFO")
            return True
        except Exception as e:
            self.log(f"Failed to cleanup checkout: {e}", "WARN")
            return False

    async def implement_and_checkin(self, spec: Dict, language: str) -> bool:
        """
        Full implementation cycle with retry logic:
        1. Checkout
        2. Generate files
        3. Validate
        4. Fix if needed (retry up to MAX_VALIDATION_RETRIES)
        5. Checkin
        """
        widget_id = spec["widget_id"]

        # Don't modify widget_id - use language subdirectories instead
        # This keeps filenames consistent and lets cartographer.py handle suffixes at checkin
        widget_id_lang = widget_id

        self.log(f"Starting implementation: {widget_id_lang}")

        # Step 1: Checkout with language subdirectory
        # Use --target to put each language in its own subdirectory
        checkout_target = f"checkouts/{language}/{widget_id_lang}"
        checkout_cmd = [
            "cartographer", "checkout", widget_id_lang,
            "--new",
            "--name", spec.get("widget_name", widget_id_lang),
            "--type", "widget",
            "--target", checkout_target
        ]

        success, output = self.run_cartographer_command(checkout_cmd)
        if not success:
            self.log(f"Checkout failed: {output}", "ERROR")
            return False

        # Step 2: Generate and write files
        # Mark as mixed-language if implementing in a non-native language
        native_language = spec.get("language", "python")
        is_mixed = language != native_language

        files = await self.implement_widget_files(spec, language, is_mixed_language=is_mixed)
        if not files:
            self.log("Failed to generate files", "ERROR")
            return False

        self.log(f"Files dict has keys: {list(files.keys())}", "INFO")
        checkout_dir = self.write_widget_files(widget_id_lang, files, language, spec=spec)
        self.log(f"Files written to: {checkout_dir}", "INFO")

        # Step 2.5: HYDRATE widget.json with actual implementation details
        self.log(f"Step 2.5: Hydrating widget.json with actual implementation...", "INFO")
        try:
            # Extract actual content from generated files
            src_content = files.get("src_file", {}).get("content", "") or "".join(
                f.get("content", "") for f in files.get("src_files", [])
            )
            test_content = files.get("test_file", {}).get("content", "")
            example_content = files.get("example_file", {}).get("content", "")

            # Hydrate widget.json
            hydrated_json = self.hydrate_widget_json(
                files["widget_json"],
                spec,
                language,
                src_content,
                test_content,
                example_content
            )

            # Update files dict and rewrite widget.json
            files["widget_json"] = hydrated_json
            widget_json_path = checkout_dir / "widget.json"
            widget_json_path.write_text(files["widget_json"])

        except Exception as e:
            self.log(f"Hydration warning (non-fatal): {e}", "WARN")

        # Step 3: Validation loop with retries
        for attempt in range(MAX_VALIDATION_RETRIES):
            self.log(f"Validation attempt {attempt + 1}/{MAX_VALIDATION_RETRIES}")

            # Run validate with --path (cartographer now runs pytest from widget directory internally)
            validate_cmd = ["cartographer", "validate", "--path", str(checkout_dir)]
            self.log(f"  Running validation on: {checkout_dir}", "INFO")
            success, output = self.run_cartographer_command(validate_cmd, timeout=120)

            # Debug log validation results
            if self.debug:
                self.debug_log(f"VALIDATION ATTEMPT {attempt + 1}", {
                    "widget_id": widget_id_lang,
                    "attempt": attempt + 1,
                    "command": " ".join(validate_cmd),
                    "command_success": success,
                    "validation_output": output
                })

            # Check if validation actually passed by parsing JSON output
            validation_passed = False
            if success and output:
                try:
                    # Try to extract JSON from output
                    import re
                    json_match = re.search(r'\{[^{]*"status"[^}]*\}', output)
                    if json_match:
                        result = json.loads(json_match.group())
                        validation_passed = result.get("status") != "error"
                    else:
                        # If no JSON found but command succeeded, assume pass
                        validation_passed = "✅ VALIDATION PASSED" in output or "VALIDATION PASSED" in output
                except:
                    # Fallback: check for success indicators in text
                    validation_passed = "✅ VALIDATION PASSED" in output or "VALIDATION PASSED" in output

            if validation_passed:
                self.log(f"Validation passed!", "SUCCESS")
                if self.debug:
                    self.debug_log("VALIDATION SUCCESS", {
                        "widget_id": widget_id_lang,
                        "attempt": attempt + 1
                    })
                break

            self.log(f"Validation failed, fixing...", "WARN")

            # Debug: Show what we're passing to error recovery
            if self.debug:
                self.debug_log(f"PRE-FIX VALIDATION OUTPUT", {
                    "output_length": len(output),
                    "output_preview": output[:1000] if output else "EMPTY",
                    "output_repr": repr(output[:500])
                })

            # Ask LLM to fix errors using holistic approach (full widget context)
            fixed_files = await self.fix_validation_errors_holistic(spec, language, files, output)
            if not fixed_files:
                self.log(f"Failed to generate fixes", "ERROR")
                continue

            # Write fixed files
            files = fixed_files
            self.write_widget_files(widget_id_lang, files, language, spec=spec)
        else:
            self.log(f"Validation failed after {MAX_VALIDATION_RETRIES} attempts", "ERROR")
            # Move failed widget to failed directory
            self._cleanup_checkout(widget_id_lang, language)
            return False

        # Step 4: Checkin
        checkin_cmd = [
            "cartographer", "checkin", str(checkout_dir),
            "--reason", f"Auto-generated {language} implementation by widget factory"
        ]

        success, output = self.run_cartographer_command(checkin_cmd, timeout=60)
        if success:
            self.log(f"Successfully checked in {widget_id_lang}!", "SUCCESS")
            self.generated_count += 1
            return True
        else:
            self.log(f"Checkin failed: {output}", "ERROR")
            # Move failed widget to failed directory
            self._cleanup_checkout(widget_id_lang, language)
            return False

    # ========================================================================
    # Main Loop
    # ========================================================================
    async def run_overnight(
        self,
        target_count: int = TARGET_WIDGET_COUNT,
        native_only: bool = False
    ):
        """
        Multi-Language Widget Factory Workflow:

        ARCHITECTURE:
        1. Generate ONE unique widget idea
        2. Implement sequentially: Python → JavaScript → TypeScript → Go → Rust
        3. Each language has comprehensive design guidelines
        4. If checkin fails → move to failed directory and clean up
        5. Continue to next language regardless of failures
        6. Only count as success if PRIMARY language succeeds

        Args:
            target_count: Number of UNIQUE IDEAS to generate (each with multi-language implementations)
            native_only: If True, only implement in native language (skip cross-language)
        """
        self.log(f"🚀 Multi-Language Widget Factory Started")
        self.log(f"📡 LLM Server: {LLAMA_URL}")
        self.log(f"🎯 Target: {target_count} unique widget ideas")
        self.log(f"🌐 Language Order: {' → '.join(LANGUAGE_ORDER)}")
        self.log(f"📦 Mode: {'Native-only' if native_only else 'Multi-language'}")

        # Health check
        try:
            if isinstance(self.client, GrokClient):
                # GrokClient doesn't have health_check, just test with a quick call
                self.log(f"✅ Using xAI Grok API: {self.client.default_model}", "SUCCESS")
            else:
                health = await self.client.health_check()
                if not health["available"]:
                    self.log(f"❌ LLM server not available: {health.get('error')}", "ERROR")
                    return
                self.log(f"✅ LLM server healthy", "SUCCESS")
        except Exception as e:
            self.log(f"❌ Health check failed: {e}", "ERROR")
            return

        ideas_completed = 0

        while ideas_completed < target_count:
            self.log(f"\n{'='*80}")
            self.log(f"📊 Progress: {ideas_completed}/{target_count} unique ideas completed")
            self.log(f"{'='*80}\n")

            # ================================================================
            # PHASE 1: Generate ONE Widget Idea (Fresh Context)
            # ================================================================
            self.log(f"💡 PHASE 1: Generating new widget idea...")
            spec = await self.generate_widget_idea()
            if not spec:
                self.log("Failed to generate idea, retrying...", "WARN")
                await asyncio.sleep(5)
                continue

            widget_base_name = spec['widget_id']
            self.log(f"✅ Generated idea: {widget_base_name}", "SUCCESS")
            self.log(f"   Name: {spec.get('widget_name', widget_base_name)}", "INFO")
            self.log(f"   Category: {spec.get('category', 'N/A')}", "INFO")

            # Track success per language
            language_results = {}

            # ================================================================
            # PHASE 2: Sequential Multi-Language Implementation
            # ================================================================
            self.log(f"\n🌐 PHASE 2: Multi-Language Implementation")
            self.log(f"   Languages to implement: {' → '.join(LANGUAGE_ORDER)}")

            for idx, language in enumerate(LANGUAGE_ORDER, 1):
                self.log(f"\n{'-'*80}")
                self.log(f"🔧 [{idx}/{len(LANGUAGE_ORDER)}] Implementing in {language.upper()}...")
                self.log(f"{'-'*80}")

                # Show language guidelines being applied
                guidelines_info = LANGUAGE_GUIDELINES.get(language, {})
                self.log(f"   Testing: {guidelines_info.get('testing_framework', 'N/A')}", "INFO")

                # Implement and checkin
                success = await self.implement_and_checkin(spec, language)
                language_results[language] = success

                if success:
                    self.log(f"✅ {language.upper()} implementation successful!", "SUCCESS")
                else:
                    self.log(f"❌ {language.upper()} implementation failed (moved to failed directory)", "ERROR")

                # Log current status
                successes = sum(1 for v in language_results.values() if v)
                failures = len(language_results) - successes
                self.log(f"   Status so far: {successes} succeeded, {failures} failed", "INFO")

                # Optional: break early if native-only mode
                if native_only and idx == 1:
                    self.log(f"🛑 Native-only mode: stopping after {LANGUAGE_ORDER[0]}", "INFO")
                    break

            # ================================================================
            # PHASE 3: Summary & Decision
            # ================================================================
            self.log(f"\n📋 SUMMARY for {widget_base_name}:")
            for lang, result in language_results.items():
                status = "✅ SUCCESS" if result else "❌ FAILED"
                self.log(f"   {lang:12s}: {status}", "INFO")

            # Count as completed if PRIMARY language (first in order) succeeded
            primary_language = LANGUAGE_ORDER[0]
            if language_results.get(primary_language, False):
                ideas_completed += 1
                self.log(f"\n🎉 Widget idea COMPLETED: {widget_base_name}", "SUCCESS")
                self.log(f"   Primary language ({primary_language}) succeeded", "SUCCESS")
            else:
                self.log(f"\n⚠️  Widget idea FAILED: {widget_base_name}", "WARN")
                self.log(f"   Primary language ({primary_language}) failed", "WARN")

        self.log(f"\n{'='*80}")
        self.log(f"🎉 Factory Complete!")
        self.log(f"{'='*80}")
        self.log(f"✅ Unique ideas completed: {ideas_completed}/{target_count}", "SUCCESS")
        self.log(f"📦 Total widgets generated: {self.generated_count}", "SUCCESS")
        self.log(f"📋 Log file: {self.log_file}", "INFO")
        self.log(f"📁 Failed widgets: {FAILED_DIR}", "INFO")


# ============================================================================
# CLI Entry Point
# ============================================================================
async def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Multi-Language Widget Factory - Generates widgets across Python, JavaScript, TypeScript, Go, Rust",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
WORKFLOW:
  1. Generate ONE unique widget idea
  2. Implement sequentially: Python → JavaScript → TypeScript → Go → Rust
  3. Each language follows comprehensive design guidelines
  4. Failed checkins moved to ./failed_widgets/ directory
  5. Continue to next language regardless of failures
  6. Success = primary language (Python) passes validation

EXAMPLES:
  # Generate 5 widget ideas in all languages
  python widget_factory.py --target 5

  # Python only (skip other languages)
  python widget_factory.py --target 10 --native-only

  # Test with debug output
  python widget_factory.py --test --debug
        """
    )
    parser.add_argument("--target", type=int, default=TARGET_WIDGET_COUNT,
                       help="Target number of UNIQUE IDEAS to generate (default: %(default)s)")
    parser.add_argument("--url", type=str, default=LLAMA_URL,
                       help="LLM server URL (default: %(default)s)")
    parser.add_argument("--model-profile", type=str, default="default",
                       help="Model profile: default, nemotron-nano, llama3, deepseek-coder, qwen-coder, grok-4-fast, grok-4-reasoning")
    parser.add_argument("--native-only", action="store_true",
                       help="Only implement in Python (skip JavaScript, TypeScript, Go, Rust)")
    parser.add_argument("--test", action="store_true",
                       help="Test mode: generate only 1 widget idea and exit (no implementation)")
    parser.add_argument("--health-check", action="store_true",
                       help="Check LLM server health and exit")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug mode: log all LLM requests/responses and validation errors")

    args = parser.parse_args()

    factory = WidgetFactory(llama_url=args.url, model_profile=args.model_profile, debug=args.debug)

    # Health check mode
    if args.health_check:
        print("🔍 Checking LLM server health...")
        try:
            if isinstance(factory.client, GrokClient):
                # For GrokClient, do a simple test call
                print(f"✅ GrokClient configured with model: {factory.client.default_model}")
                print("   Testing API connection...")
                test_result = await factory.client.chat(
                    messages=[{"role": "user", "content": "Say 'OK' if you can hear me."}],
                    max_tokens=10
                )
                if test_result.get("content"):
                    print(f"✅ xAI API is responding: {test_result['content'][:50]}")
                else:
                    print("❌ xAI API returned empty response")
                    sys.exit(1)
            else:
                # LlamaClient health check
                health = await factory.client.health_check()
                if health["available"]:
                    print(f"✅ LLM server is healthy at {args.url}")
                    props = await factory.client.get_server_properties()
                    if props:
                        ctx_size = props.get("default_generation_settings", {}).get("n_ctx")
                        print(f"📊 Context size: {ctx_size}")
                else:
                    print(f"❌ LLM server unavailable: {health.get('error')}")
                    sys.exit(1)
            return
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            sys.exit(1)

    # Test mode
    if args.test:
        print("🧪 TEST MODE: Generating one widget idea...")
        spec = await factory.generate_widget_idea()
        if spec:
            print("✅ Successfully generated widget idea:")
            print(json.dumps(spec, indent=2))
            print("\n💡 To implement this widget, run without --test flag")
        else:
            print("❌ Failed to generate widget idea")
            sys.exit(1)
        return

    # Normal factory mode
    await factory.run_overnight(target_count=args.target, native_only=args.native_only)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Factory stopped by user")
    except Exception as e:
        print(f"\n\n❌ Factory crashed: {e}")
        raise
