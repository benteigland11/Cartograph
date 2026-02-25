"""
Language-specific file templates for widget scaffolding.

Each function writes starter src/, tests/, and examples/ files for a given language.
None of these need the Cartographer instance — they just write files to disk.
"""

import json
import os
import re


def python(target_dir, module_name, display_name, **_):
    with open(os.path.join(target_dir, "src", "__init__.py"), "w") as f:
        f.write(f"from .{module_name} import {module_name}\n")
        f.write(f"__all__ = ['{module_name}']\n")
    with open(os.path.join(target_dir, "src", f"{module_name}.py"), "w") as f:
        f.write(f'def {module_name}(value):\n    """{display_name}: process a value."""\n    return value\n')
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f"import sys, os\n"
            f"sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
            f"from {module_name} import {module_name}\n\n\n"
            f"def test_{module_name}_returns_value():\n"
            f"    assert {module_name}(42) == 42\n"
        )
    with open(os.path.join(target_dir, "examples", "example_usage.py"), "w") as f:
        f.write(
            f'"""\n'
            f"Example usage of {display_name}.\n\n"
            f"This file must run cleanly with no external dependencies or network calls.\n"
            f"Use fake/hardcoded data to demonstrate the widget's logic.\n"
            f'"""\n'
            f"import sys, os\n"
            f"sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
            f"from {module_name} import {module_name}\n\n"
            f"# [TODO] Replace with a realistic call using fake data\n"
            f'result = {module_name}("hello")\n'
            f'print(f"Result: {{result}}")\n'
        )


def javascript(target_dir, module_name, display_name, item_id, **_):
    func_name = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), module_name)
    with open(os.path.join(target_dir, "src", "index.js"), "w") as f:
        f.write(
            f"/**\n * {display_name}: process a value.\n"
            f" * @param {{*}} value\n * @returns {{*}}\n */\n"
            f"export function {func_name}(value) {{\n  return value;\n}}\n"
        )
    with open(os.path.join(target_dir, "tests", "test_index.js"), "w") as f:
        f.write(
            f"import {{ describe, it, expect }} from 'vitest';\n"
            f"import {{ {func_name} }} from '../src/index.js';\n\n"
            f"describe('{func_name}', () => {{\n"
            f"  it('should return the value', () => {{\n"
            f"    expect({func_name}(42)).toBe(42);\n"
            f"  }});\n}});\n"
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.js"), "w") as f:
        f.write(
            f"import {{ {func_name} }} from '../src/index.js';\n\n"
            f"const result = {func_name}('hello');\nconsole.log('Result:', result);\n"
        )
    with open(os.path.join(target_dir, "package.json"), "w") as f:
        json.dump({"name": item_id, "version": "1.0.0", "type": "module",
                   "scripts": {"test": "vitest run"},
                   "devDependencies": {"vitest": "^1.0.0"}}, f, indent=2)


def typescript(target_dir, module_name, display_name, item_id, **_):
    func_name = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), module_name)
    with open(os.path.join(target_dir, "src", "index.ts"), "w") as f:
        f.write(
            f"/**\n * {display_name}: process a value.\n */\n"
            f"export function {func_name}(value: unknown): unknown {{\n  return value;\n}}\n"
        )
    with open(os.path.join(target_dir, "tests", "test_index.ts"), "w") as f:
        f.write(
            f"import {{ describe, it, expect }} from 'vitest';\n"
            f"import {{ {func_name} }} from '../src/index';\n\n"
            f"describe('{func_name}', () => {{\n"
            f"  it('should return the value', () => {{\n"
            f"    expect({func_name}(42)).toBe(42);\n"
            f"  }});\n}});\n"
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.ts"), "w") as f:
        f.write(
            f"import {{ {func_name} }} from '../src/index';\n\n"
            f"const result = {func_name}('hello');\nconsole.log('Result:', result);\n"
        )
    with open(os.path.join(target_dir, "package.json"), "w") as f:
        json.dump({"name": item_id, "version": "1.0.0", "type": "module",
                   "scripts": {"test": "vitest run"},
                   "devDependencies": {"vitest": "^1.0.0", "typescript": "^5.0.0"}}, f, indent=2)
    with open(os.path.join(target_dir, "tsconfig.json"), "w") as f:
        json.dump({"compilerOptions": {"target": "ES2020", "module": "ESNext",
                                       "moduleResolution": "bundler", "strict": True,
                                       "outDir": "dist", "rootDir": "src"},
                   "include": ["src"]}, f, indent=2)


def go(target_dir, module_name, display_name, item_id, **_):
    pkg_name = module_name.replace("_", "").lower()
    func_name = module_name.replace("_", " ").title().replace(" ", "")
    with open(os.path.join(target_dir, "src", f"{module_name}.go"), "w") as f:
        f.write(
            f"package {pkg_name}\n\n"
            f"// {func_name} processes a value.\n"
            f"func {func_name}(value string) string {{\n\treturn value\n}}\n"
        )
    with open(os.path.join(target_dir, "tests", f"{module_name}_test.go"), "w") as f:
        f.write(
            f'package {pkg_name}\n\nimport "testing"\n\n'
            f"func Test{func_name}(t *testing.T) {{\n"
            f'\tresult := {func_name}("hello")\n'
            f'\tif result != "hello" {{\n'
            f'\t\tt.Errorf("expected hello, got %s", result)\n'
            f"\t}}\n}}\n"
        )
    with open(os.path.join(target_dir, "examples", "example_test.go"), "w") as f:
        f.write(
            f'package {pkg_name}_test\n\nimport "fmt"\n\n'
            f"func Example{func_name}() {{\n"
            f"\t// result := {pkg_name}.{func_name}(\"hello\")\n"
            f'\tfmt.Println("hello")\n\t// Output: hello\n}}\n'
        )
    with open(os.path.join(target_dir, "go.mod"), "w") as f:
        f.write(f"module {item_id}\n\ngo 1.21\n")


def rust(target_dir, module_name, display_name, item_id, **_):
    func_name = module_name
    crate_name = item_id.replace("-", "_") if item_id else module_name
    with open(os.path.join(target_dir, "src", "lib.rs"), "w") as f:
        f.write(
            f"/// {display_name}: process a value.\n"
            f"pub fn {func_name}(value: &str) -> String {{\n    value.to_string()\n}}\n\n"
            f"#[cfg(test)]\nmod tests {{\n    use super::*;\n\n"
            f"    #[test]\n    fn test_{func_name}() {{\n"
            f'        assert_eq!({func_name}("hello"), "hello");\n    }}\n}}\n'
        )
    with open(os.path.join(target_dir, "tests", "integration_test.rs"), "w") as f:
        f.write(
            f"use {crate_name}::{func_name};\n\n#[test]\n"
            f"fn test_{func_name}_integration() {{\n"
            f'    let result = {func_name}("world");\n'
            f'    assert_eq!(result, "world");\n}}\n'
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.rs"), "w") as f:
        f.write(
            f"use {crate_name}::{func_name};\n\nfn main() {{\n"
            f'    let result = {func_name}("hello");\n'
            f'    println!("Result: {{}}", result);\n}}\n'
        )
    with open(os.path.join(target_dir, "Cargo.toml"), "w") as f:
        f.write(
            f'[package]\nname = "{item_id}"\nversion = "1.0.0"\nedition = "2021"\n\n'
            f'[lib]\npath = "src/lib.rs"\n\n'
            f'[[example]]\nname = "basic_usage"\npath = "examples/basic_usage.rs"\n'
        )


def hip(target_dir, module_name, display_name, gpu_targets=None, **_):
    targets_str = ", ".join(gpu_targets) if gpu_targets else "gfx1100"
    first_target = gpu_targets[0] if gpu_targets else "gfx1100"
    with open(os.path.join(target_dir, "src", f"{module_name}.hip"), "w") as f:
        f.write(
            f'#include <hip/hip_runtime.h>\n#include "{module_name}.h"\n\n'
            f"/// {display_name}: GPU kernel\n"
            f"__global__ void {module_name}_kernel(float* output, const float* input, int n) {{\n"
            f"    int idx = blockIdx.x * blockDim.x + threadIdx.x;\n"
            f"    if (idx < n) {{ output[idx] = input[idx]; }}\n}}\n\n"
            f"void {module_name}_launch(float* output, const float* input, int n, hipStream_t stream) {{\n"
            f"    int block_size = 256;\n"
            f"    int grid_size = (n + block_size - 1) / block_size;\n"
            f"    hipLaunchKernelGGL({module_name}_kernel, dim3(grid_size), dim3(block_size), 0, stream,\n"
            f"                       output, input, n);\n}}\n"
        )
    with open(os.path.join(target_dir, "src", f"{module_name}.h"), "w") as f:
        f.write(
            f"#pragma once\n#include <hip/hip_runtime.h>\n\n"
            f"/// {display_name}: host-side launch wrapper\n"
            f"void {module_name}_launch(float* output, const float* input, int n, hipStream_t stream = 0);\n"
        )
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f'"""Test harness for {display_name} HIP kernel."""\n'
            f"import subprocess, os, tempfile\n\n\n"
            f"def test_{module_name}_compiles():\n"
            f"    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"    src_file = os.path.join(src_dir, '{module_name}.hip')\n"
            f"    assert os.path.exists(src_file)\n"
            f"    with tempfile.TemporaryDirectory() as tmpdir:\n"
            f"        out_file = os.path.join(tmpdir, '{module_name}.so')\n"
            f"        cmd = ['hipcc', '-O2', '--offload-arch={first_target}',\n"
            f"               '-shared', '-fPIC', src_file, '-o', out_file]\n"
            f"        result = subprocess.run(cmd, capture_output=True, text=True)\n"
            f"        assert result.returncode == 0, f'Compilation failed:\\n{{result.stderr}}'\n"
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.py"), "w") as f:
        f.write(
            f'"""Example: compile and use {display_name}. Targets: {targets_str}"""\n'
            f"import subprocess, os\n"
            f"src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"src_file = os.path.join(src_dir, '{module_name}.hip')\n"
            f"out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')\n"
            f"os.makedirs(os.path.dirname(out_file), exist_ok=True)\n"
            f"subprocess.run(['hipcc', '-O2', '--offload-arch={first_target}',\n"
            f"                '-shared', '-fPIC', src_file, '-o', out_file], check=True)\n"
            f'print(f"Built: {{out_file}}")\n'
        )


def cpp(target_dir, module_name, display_name, **_):
    with open(os.path.join(target_dir, "src", f"{module_name}.cpp"), "w") as f:
        f.write(f'#include "{module_name}.h"\n\nint {module_name}(int value) {{ return value; }}\n')
    with open(os.path.join(target_dir, "src", f"{module_name}.h"), "w") as f:
        f.write(f"#pragma once\n\nint {module_name}(int value);\n")
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f'"""Test harness for {display_name} C++ widget."""\n'
            f"import subprocess, os, tempfile\n\n\n"
            f"def test_{module_name}_compiles_and_runs():\n"
            f"    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"    src_file = os.path.join(src_dir, '{module_name}.cpp')\n"
            f"    with tempfile.TemporaryDirectory() as tmpdir:\n"
            f"        driver = os.path.join(tmpdir, 'driver.cpp')\n"
            f"        with open(driver, 'w') as f:\n"
            f'            f.write(\'#include <iostream>\\n#include "{module_name}.h"\\n\'\n'
            f"                    'int main() {{ int r = {module_name}(42); '\n"
            f"                    'if (r != 42) {{ std::cerr << \"FAIL\"; return 1; }} '\n"
            f"                    'std::cout << \"PASS\"; return 0; }}')\n"
            f"        out_bin = os.path.join(tmpdir, 'test_bin')\n"
            f"        res = subprocess.run(['g++', '-std=c++17', '-I', src_dir, src_file, driver, '-o', out_bin],\n"
            f"                             capture_output=True, text=True)\n"
            f"        assert res.returncode == 0, f'Compile failed:\\n{{res.stderr}}'\n"
            f"        run = subprocess.run([out_bin], capture_output=True, text=True)\n"
            f"        assert run.returncode == 0\n"
            f"        assert 'PASS' in run.stdout\n"
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.py"), "w") as f:
        f.write(
            f'"""Example: compile {display_name} as a shared library."""\n'
            f"import subprocess, os\n"
            f"src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')\n"
            f"os.makedirs(os.path.dirname(out_file), exist_ok=True)\n"
            f"subprocess.run(['g++', '-std=c++17', '-shared', '-fPIC',\n"
            f"                os.path.join(src_dir, '{module_name}.cpp'), '-o', out_file], check=True)\n"
            f'print(f"Built: {{out_file}}")\n'
        )


def c(target_dir, module_name, display_name, **_):
    with open(os.path.join(target_dir, "src", f"{module_name}.c"), "w") as f:
        f.write(f'#include "{module_name}.h"\n\nint {module_name}(int value) {{ return value; }}\n')
    with open(os.path.join(target_dir, "src", f"{module_name}.h"), "w") as f:
        f.write(f"#pragma once\n\nint {module_name}(int value);\n")
    with open(os.path.join(target_dir, "tests", f"test_{module_name}.py"), "w") as f:
        f.write(
            f'"""Test harness for {display_name} C widget."""\n'
            f"import subprocess, os, tempfile\n\n\n"
            f"def test_{module_name}_compiles_and_runs():\n"
            f"    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"    src_file = os.path.join(src_dir, '{module_name}.c')\n"
            f"    with tempfile.TemporaryDirectory() as tmpdir:\n"
            f"        driver = os.path.join(tmpdir, 'driver.c')\n"
            f"        with open(driver, 'w') as f:\n"
            f'            f.write(\'#include <stdio.h>\\n#include "{module_name}.h"\\n\'\n'
            f"                    'int main() {{ int r = {module_name}(42); '\n"
            f"                    'if (r != 42) {{ fprintf(stderr, \"FAIL\\\\n\"); return 1; }} '\n"
            f"                    'printf(\"PASS\\\\n\"); return 0; }}')\n"
            f"        out_bin = os.path.join(tmpdir, 'test_bin')\n"
            f"        res = subprocess.run(['gcc', '-std=c11', '-I', src_dir, src_file, driver, '-o', out_bin],\n"
            f"                             capture_output=True, text=True)\n"
            f"        assert res.returncode == 0, f'Compile failed:\\n{{res.stderr}}'\n"
            f"        run = subprocess.run([out_bin], capture_output=True, text=True)\n"
            f"        assert run.returncode == 0\n"
            f"        assert 'PASS' in run.stdout\n"
        )
    with open(os.path.join(target_dir, "examples", "basic_usage.py"), "w") as f:
        f.write(
            f'"""Example: compile {display_name} as a shared library."""\n'
            f"import subprocess, os\n"
            f"src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')\n"
            f"out_file = os.path.join(src_dir, '..', 'build', '{module_name}.so')\n"
            f"os.makedirs(os.path.dirname(out_file), exist_ok=True)\n"
            f"subprocess.run(['gcc', '-std=c11', '-shared', '-fPIC',\n"
            f"                os.path.join(src_dir, '{module_name}.c'), '-o', out_file], check=True)\n"
            f'print(f"Built: {{out_file}}")\n'
        )


# Registry: maps normalized language name → template function
TEMPLATES = {
    "python": python,
    "javascript": javascript,
    "typescript": typescript,
    "go": go,
    "rust": rust,
    "hip": hip,
    "cpp": cpp,
    "c": c,
}
