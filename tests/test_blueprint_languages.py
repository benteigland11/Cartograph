"""End-to-end blueprint validation tests across language engines.

Each test stands up a real widget + blueprint pair on disk and runs
`validate_blueprint` from `id` to green. These are the load-bearing
proofs that v0.7's "blueprints in any language" claim actually holds:
the engine abstraction either works for that language, or the test
fails loud.

Each test is `slow` because it shells out to the language toolchain
(npm install, nimble build, composer, etc.). They are gated on the
toolchain being installed - skipped otherwise so CI without the
toolchain stays green.
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

from cartograph.engine import Cartograph
from cartograph.languages import get_engine


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

_GREET_SRC = """\
export function greet(name) {
  return `hello, ${name}`;
}
"""

_GREET_TEST = """\
import { describe, it, expect } from 'vitest';
import { greet } from '../src/greet.js';

describe('greet', () => {
  it('returns a greeting', () => {
    expect(greet('world')).toBe('hello, world');
  });
});
"""

_GREET_EXAMPLE = """\
import { greet } from '../src/greet.js';
console.log(greet('world'));
"""

_VITEST_CONFIG = """\
import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: { include: ['tests/**/*.js'] },
});
"""

_SHOUTER_SRC = """\
import { greet } from '../cg/frontend-greet-javascript/src/greet.js';

export function shout(name) {
  return greet(name).toUpperCase();
}
"""

_SHOUTER_TEST = """\
import { describe, it, expect } from 'vitest';
import { shout } from '../src/shouter.js';

describe('shout', () => {
  it('uppercases the greeting', () => {
    expect(shout('world')).toBe('HELLO, WORLD');
  });
});
"""

_SHOUTER_EXAMPLE = """\
import { shout } from '../src/shouter.js';
console.log(shout('world'));
"""


def _write_js_widget(project_dir: str) -> str:
    """Write a real, runnable JS widget into <project>/cg/frontend-greet-javascript/."""
    wdir = os.path.join(project_dir, "cg", "frontend-greet-javascript")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "frontend-greet-javascript",
            "name": "greet",
            "version": "1.0.0",
            "domain": "frontend",
            "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "javascript", "dependencies": []},
        "description": "Returns a friendly greeting string.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    pkg = {
        "name": "frontend-greet-javascript",
        "version": "1.0.0",
        "type": "module",
        "dependencies": {},
        "devDependencies": {"vitest": "^1.0.0", "@vitest/coverage-v8": "^1.0.0"},
    }
    with open(os.path.join(wdir, "package.json"), "w") as f:
        json.dump(pkg, f, indent=2)
    with open(os.path.join(wdir, "vitest.config.js"), "w") as f:
        f.write(_VITEST_CONFIG)
    with open(os.path.join(wdir, "src", "greet.js"), "w") as f:
        f.write(_GREET_SRC)
    with open(os.path.join(wdir, "tests", "test_greet.js"), "w") as f:
        f.write(_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.js"), "w") as f:
        f.write(_GREET_EXAMPLE)
    return wdir


def _write_js_blueprint(project_dir: str) -> str:
    """Write a JS blueprint that depends on the greet widget."""
    bp = os.path.join(project_dir, "cg", "bp-shouter-javascript")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-javascript",
        "name": "shouter",
        "language": "javascript",
        "version": "0.1.0",
        "description": "Uppercases a greeting via the greet widget.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "frontend-greet-javascript", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    pkg = {
        "name": "bp-shouter-javascript",
        "version": "0.1.0",
        "type": "module",
        "dependencies": {},
        "devDependencies": {"vitest": "^1.0.0", "@vitest/coverage-v8": "^1.0.0"},
    }
    with open(os.path.join(bp, "package.json"), "w") as f:
        json.dump(pkg, f, indent=2)
    with open(os.path.join(bp, "vitest.config.js"), "w") as f:
        f.write(_VITEST_CONFIG)
    with open(os.path.join(bp, "src", "shouter.js"), "w") as f:
        f.write(_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "test_shouter.js"), "w") as f:
        f.write(_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.js"), "w") as f:
        f.write(_SHOUTER_EXAMPLE)
    return bp


@pytest.fixture
def carto(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    return Cartograph(library_path=str(lib))


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


# ---------------------------------------------------------------------------
# Nim
# ---------------------------------------------------------------------------

_NIM_GREET_NIMBLE = """\
version = "1.0.0"
author = "Test"
description = "greet"
license = "MIT"
srcDir = "src"
requires "nim >= 2.0.0"

task test, "run tests":
  for f in listFiles("tests"):
    if f.endsWith(".nim"):
      exec "nimble c -r --path:src " & f
"""

_NIM_GREET_SRC = """\
func greet*(name: string): string =
  "hello, " & name
"""

_NIM_GREET_TEST = """\
import std/unittest
import greet_lib

suite "greet":
  test "returns greeting":
    check greet("world") == "hello, world"
"""

_NIM_GREET_EXAMPLE = """\
import greet_lib
let r = greet("world")
discard r
"""

_NIM_SHOUTER_NIMBLE = """\
version = "0.1.0"
author = "Test"
description = "shouter"
license = "MIT"
srcDir = "src"
requires "nim >= 2.0.0"

task test, "run tests":
  for f in listFiles("tests"):
    if f.endsWith(".nim"):
      exec "nimble c -r --path:src --path:cg/frontend_greet_nim/src " & f
"""

_NIM_SHOUTER_SRC = """\
import greet_lib
import std/strutils

func shout*(name: string): string =
  greet(name).toUpperAscii
"""

_NIM_SHOUTER_TEST = """\
import std/unittest
import shouter_lib

suite "shout":
  test "uppercases":
    check shout("world") == "HELLO, WORLD"
"""

_NIM_SHOUTER_EXAMPLE = """\
import shouter_lib
let r = shout("world")
discard r
"""


def _write_nim_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "frontend_greet_nim")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "frontend-greet-nim", "name": "greet", "version": "1.0.0",
            "domain": "frontend", "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "nim", "dependencies": []},
        "description": "Returns a greeting string.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "greet.nimble"), "w") as f:
        f.write(_NIM_GREET_NIMBLE)
    with open(os.path.join(wdir, "src", "greet_lib.nim"), "w") as f:
        f.write(_NIM_GREET_SRC)
    with open(os.path.join(wdir, "tests", "test_greet.nim"), "w") as f:
        f.write(_NIM_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.nim"), "w") as f:
        f.write(_NIM_GREET_EXAMPLE)
    return wdir


def _write_nim_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp_shouter_nim")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-nim",
        "name": "shouter",
        "language": "nim",
        "version": "0.1.0",
        "description": "Uppercases a greeting via the greet widget.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "frontend-greet-nim", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "shouter.nimble"), "w") as f:
        f.write(_NIM_SHOUTER_NIMBLE)
    with open(os.path.join(bp, "src", "shouter_lib.nim"), "w") as f:
        f.write(_NIM_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "test_shouter.nim"), "w") as f:
        f.write(_NIM_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.nim"), "w") as f:
        f.write(_NIM_SHOUTER_EXAMPLE)
    return bp


@pytest.mark.slow
def test_nim_blueprint_validates_end_to_end(carto, project):
    """A Nim blueprint composing a Nim widget validates green."""
    if not shutil.which("nim") or not shutil.which("nimble"):
        pytest.skip("nim/nimble not available")
    engine = get_engine("nim")
    if engine is None or not engine.supported:
        pytest.skip("nim engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"nim engine not ready: {msg}")

    _write_nim_widget(str(project))
    bp = _write_nim_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-nim"


@pytest.mark.slow
def test_javascript_blueprint_validates_end_to_end(carto, project):
    """A JS blueprint composing a JS widget validates green from id to id.

    Exercises the full engine surface for JS: install_deps (npm),
    run_tests (vitest), run_blueprint_example (node), src import
    detection, sandbox copy of the dep widget, and the schema check.
    """
    if not shutil.which("npm") or not shutil.which("node"):
        pytest.skip("npm/node not available")
    engine = get_engine("javascript")
    if engine is None or not engine.supported:
        pytest.skip("javascript engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"javascript engine not ready: {msg}")

    _write_js_widget(str(project))
    bp = _write_js_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    if res.get("status") != "success":
        # Print the full vitest output to captured stdout so it survives
        # pytest's short-tb assertion repr truncation. The test_output
        # field carries up to 3000 chars of combined stdout+stderr.
        print("---VITEST FULL OUTPUT---")
        print("message:", res.get("message", "<no message>"))
        print("test_output:")
        print(res.get("test_output", "<no test_output>"))
        print("---END VITEST OUTPUT---")
    assert res.get("status") == "success", res
    assert res["kind"] == "blueprint"
    assert res["id"] == "bp-shouter-javascript"
    assert res["language"] == "javascript"
    assert any(d["id"] == "frontend-greet-javascript" for d in res["deps"])


# ---------------------------------------------------------------------------
# Terraform
# ---------------------------------------------------------------------------

_TF_VERSIONS = """\
terraform {
  required_version = ">= 1.0"
}
"""

_TF_GREET_MAIN = """\
variable "name" {
  type    = string
  default = "world"
}

output "greeting" {
  value = "hello, ${var.name}"
}
"""

_TF_GREET_TEST = """\
module "greet" {
  source = "../src"
  name   = "test"
}

output "greet_check" {
  value = module.greet.greeting
}
"""

_TF_GREET_EXAMPLE = """\
module "greet" {
  source = "../src"
  name   = "world"
}

output "result" {
  value = module.greet.greeting
}
"""

_TF_SHOUTER_MAIN = """\
variable "name" {
  type    = string
  default = "world"
}

module "greet" {
  source = "../cg/infra-greet-terraform/src"
  name   = var.name
}

output "shout" {
  value = upper(module.greet.greeting)
}
"""

_TF_SHOUTER_TEST = """\
module "shouter" {
  source = "../src"
  name   = "test"
}

output "shout_check" {
  value = module.shouter.shout
}
"""

_TF_SHOUTER_EXAMPLE = """\
module "shouter" {
  source = "../src"
  name   = "world"
}

output "result" {
  value = module.shouter.shout
}
"""


def _write_tf_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "infra-greet-terraform")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "infra-greet-terraform", "name": "greet", "version": "1.0.0",
            "domain": "infra", "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "terraform", "dependencies": []},
        "description": "Outputs a greeting string.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "src", "main.tf"), "w") as f:
        f.write(_TF_GREET_MAIN)
    with open(os.path.join(wdir, "src", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    with open(os.path.join(wdir, "tests", "test_main.tf"), "w") as f:
        f.write(_TF_GREET_TEST)
    with open(os.path.join(wdir, "tests", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    with open(os.path.join(wdir, "examples", "example_usage.tf"), "w") as f:
        f.write(_TF_GREET_EXAMPLE)
    with open(os.path.join(wdir, "examples", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    return wdir


def _write_tf_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-shouter-terraform")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-terraform",
        "name": "shouter",
        "language": "terraform",
        "version": "0.1.0",
        "description": "Uppercases a greeting via the greet module.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "infra-greet-terraform", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "src", "main.tf"), "w") as f:
        f.write(_TF_SHOUTER_MAIN)
    with open(os.path.join(bp, "src", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    with open(os.path.join(bp, "tests", "test_main.tf"), "w") as f:
        f.write(_TF_SHOUTER_TEST)
    with open(os.path.join(bp, "tests", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    with open(os.path.join(bp, "examples", "example_usage.tf"), "w") as f:
        f.write(_TF_SHOUTER_EXAMPLE)
    with open(os.path.join(bp, "examples", "versions.tf"), "w") as f:
        f.write(_TF_VERSIONS)
    return bp


@pytest.mark.slow
def test_terraform_blueprint_validates_end_to_end(carto, project):
    if not shutil.which("terraform"):
        pytest.skip("terraform not available")
    engine = get_engine("terraform")
    if engine is None or not engine.supported:
        pytest.skip("terraform engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"terraform engine not ready: {msg}")

    _write_tf_widget(str(project))
    bp = _write_tf_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-terraform"


# ---------------------------------------------------------------------------
# OpenSCAD
# ---------------------------------------------------------------------------

_SCAD_GREET_SRC = """\
// greet box
module greet_box(width = 20, height = 10, depth = 5) {
  cube([width, height, depth], center = true);
}
"""

_SCAD_GREET_TEST = """\
use <../src/greet.scad>
greet_box();
greet_box(width = 5, height = 5, depth = 5);
"""

_SCAD_GREET_EXAMPLE = """\
use <../src/greet.scad>
greet_box(width = 30);
"""

_SCAD_SHOUTER_SRC = """\
// shouter wraps greet_box with a doubled width
use <../cg/modeling-greet-openscad/src/greet.scad>

module shouter_box(width = 20, height = 10, depth = 5) {
  greet_box(width = width * 2, height = height, depth = depth);
}
"""

_SCAD_SHOUTER_TEST = """\
use <../src/shouter.scad>
shouter_box();
shouter_box(width = 5);
"""

_SCAD_SHOUTER_EXAMPLE = """\
use <../src/shouter.scad>
shouter_box(width = 15);
"""


def _write_scad_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "modeling-greet-openscad")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "modeling-greet-openscad", "name": "greet", "version": "1.0.0",
            "domain": "modeling", "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "openscad", "dependencies": []},
        "description": "A parametric greet box.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "src", "greet.scad"), "w") as f:
        f.write(_SCAD_GREET_SRC)
    with open(os.path.join(wdir, "tests", "test_greet.scad"), "w") as f:
        f.write(_SCAD_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.scad"), "w") as f:
        f.write(_SCAD_GREET_EXAMPLE)
    return wdir


def _write_scad_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-shouter-openscad")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-openscad",
        "name": "shouter",
        "language": "openscad",
        "version": "0.1.0",
        "description": "Doubles the greet box via the greet widget.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "modeling-greet-openscad", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "src", "shouter.scad"), "w") as f:
        f.write(_SCAD_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "test_shouter.scad"), "w") as f:
        f.write(_SCAD_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.scad"), "w") as f:
        f.write(_SCAD_SHOUTER_EXAMPLE)
    return bp


@pytest.mark.slow
def test_openscad_blueprint_validates_end_to_end(carto, project):
    if not shutil.which("openscad"):
        pytest.skip("openscad not available")
    engine = get_engine("openscad")
    if engine is None or not engine.supported:
        pytest.skip("openscad engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"openscad engine not ready: {msg}")

    _write_scad_widget(str(project))
    bp = _write_scad_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-openscad"


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------

_PHP_GREET_SRC = """\
<?php
declare(strict_types=1);

namespace Cartograph\\Greet;

class Greet
{
    public function greet(string $name): string
    {
        return "hello, " . $name;
    }
}
"""

_PHP_GREET_TEST = """\
<?php
declare(strict_types=1);

use PHPUnit\\Framework\\TestCase;
use Cartograph\\Greet\\Greet;

class GreetTest extends TestCase
{
    public function test_greet_returns_string(): void
    {
        $g = new Greet();
        $this->assertSame("hello, world", $g->greet("world"));
    }
}
"""

_PHP_GREET_EXAMPLE = """\
<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

use Cartograph\\Greet\\Greet;
$g = new Greet();
echo $g->greet("world") . PHP_EOL;
"""

_PHP_GREET_COMPOSER = """\
{
    "name": "cartograph/greet",
    "type": "library",
    "require": {"php": ">=8.1"},
    "require-dev": {"phpunit/phpunit": "^11.0"},
    "autoload": {
        "psr-4": {"Cartograph\\\\Greet\\\\": "src/"}
    },
    "autoload-dev": {
        "psr-4": {"Cartograph\\\\Greet\\\\": "tests/"}
    }
}
"""

_PHP_PHPUNIT = """\
<?xml version="1.0" encoding="UTF-8"?>
<phpunit bootstrap="vendor/autoload.php" colors="true">
    <testsuites>
        <testsuite name="Widget Tests">
            <directory>tests</directory>
        </testsuite>
    </testsuites>
    <source>
        <include>
            <directory>src</directory>
        </include>
    </source>
    <coverage>
        <report>
            <text outputFile="php://stdout" showUncoveredFiles="false"/>
        </report>
    </coverage>
</phpunit>
"""

_PHP_SHOUTER_SRC = """\
<?php
declare(strict_types=1);

namespace Cartograph\\Shouter;

require_once __DIR__ . '/../cg/security-greet-php/src/Greet.php';

use Cartograph\\Greet\\Greet;

class Shouter
{
    public function shout(string $name): string
    {
        return strtoupper((new Greet())->greet($name));
    }
}
"""

_PHP_SHOUTER_TEST = """\
<?php
declare(strict_types=1);

use PHPUnit\\Framework\\TestCase;
use Cartograph\\Shouter\\Shouter;

class ShouterTest extends TestCase
{
    public function test_shout_uppercases(): void
    {
        $s = new Shouter();
        $this->assertSame("HELLO, WORLD", $s->shout("world"));
    }
}
"""

_PHP_SHOUTER_EXAMPLE = """\
<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

use Cartograph\\Shouter\\Shouter;
$s = new Shouter();
echo $s->shout("world") . PHP_EOL;
"""

_PHP_SHOUTER_COMPOSER = """\
{
    "name": "cartograph/shouter",
    "type": "library",
    "require": {"php": ">=8.1"},
    "require-dev": {"phpunit/phpunit": "^11.0"},
    "autoload": {
        "psr-4": {"Cartograph\\\\Shouter\\\\": "src/"}
    },
    "autoload-dev": {
        "psr-4": {"Cartograph\\\\Shouter\\\\": "tests/"}
    }
}
"""


def _write_php_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "security-greet-php")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "security-greet-php", "name": "greet", "version": "1.0.0",
            "domain": "security", "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "php", "dependencies": []},
        "description": "Returns a greeting string.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "composer.json"), "w") as f:
        f.write(_PHP_GREET_COMPOSER)
    with open(os.path.join(wdir, "phpunit.xml"), "w") as f:
        f.write(_PHP_PHPUNIT)
    with open(os.path.join(wdir, "src", "Greet.php"), "w") as f:
        f.write(_PHP_GREET_SRC)
    with open(os.path.join(wdir, "tests", "GreetTest.php"), "w") as f:
        f.write(_PHP_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.php"), "w") as f:
        f.write(_PHP_GREET_EXAMPLE)
    return wdir


def _write_php_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-shouter-php")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-php",
        "name": "shouter",
        "language": "php",
        "version": "0.1.0",
        "description": "Uppercases a greeting via the greet widget.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "security-greet-php", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "composer.json"), "w") as f:
        f.write(_PHP_SHOUTER_COMPOSER)
    with open(os.path.join(bp, "phpunit.xml"), "w") as f:
        f.write(_PHP_PHPUNIT)
    with open(os.path.join(bp, "src", "Shouter.php"), "w") as f:
        f.write(_PHP_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "ShouterTest.php"), "w") as f:
        f.write(_PHP_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.php"), "w") as f:
        f.write(_PHP_SHOUTER_EXAMPLE)
    return bp


@pytest.mark.slow
def test_php_blueprint_validates_end_to_end(carto, project):
    if not shutil.which("php") or not shutil.which("composer"):
        pytest.skip("php/composer not available")
    engine = get_engine("php")
    if engine is None or not engine.supported:
        pytest.skip("php engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"php engine not ready: {msg}")
    # PHP coverage requires xdebug or pcov
    optional = engine.check_optional()
    if not any(present for _, present, _ in optional):
        pytest.skip("no PHP coverage driver (xdebug/pcov)")

    _write_php_widget(str(project))
    bp = _write_php_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-php"


# ---------------------------------------------------------------------------
# SystemVerilog
# ---------------------------------------------------------------------------

_SV_GREET_SRC = """\
module greet_buf #(
    parameter int WIDTH = 8
)(
    input  logic [WIDTH-1:0] in_data,
    output logic [WIDTH-1:0] out_data
);
    assign out_data = in_data;
endmodule
"""

_SV_GREET_TEST = """\
`timescale 1ns/1ps
module test_greet;
    logic [7:0] in_data, out_data;
    greet_buf #(.WIDTH(8)) dut(.in_data(in_data), .out_data(out_data));
    initial begin
        in_data = 8'hAA;
        #1;
        if (out_data !== 8'hAA) begin
            $display("FAIL: expected AA, got %h", out_data);
            $finish(1);
        end
        $display("PASS");
        $finish;
    end
endmodule
"""

_SV_GREET_EXAMPLE = """\
`timescale 1ns/1ps
module example_usage;
    logic [7:0] in_data, out_data;
    greet_buf #(.WIDTH(8)) dut(.in_data(in_data), .out_data(out_data));
    initial begin
        in_data = 8'h55;
        #1;
        $display("out=%h", out_data);
        $finish;
    end
endmodule
"""

_SV_SHOUTER_SRC = """\
module shouter_inv #(
    parameter int WIDTH = 8
)(
    input  logic [WIDTH-1:0] in_data,
    output logic [WIDTH-1:0] out_data
);
    logic [WIDTH-1:0] buffered;
    greet_buf #(.WIDTH(WIDTH)) inner(.in_data(in_data), .out_data(buffered));
    assign out_data = ~buffered;
endmodule
"""

_SV_SHOUTER_TEST = """\
`timescale 1ns/1ps
module test_shouter;
    logic [7:0] in_data, out_data;
    shouter_inv #(.WIDTH(8)) dut(.in_data(in_data), .out_data(out_data));
    initial begin
        in_data = 8'hAA;
        #1;
        if (out_data !== 8'h55) begin
            $display("FAIL: expected 55, got %h", out_data);
            $finish(1);
        end
        $display("PASS");
        $finish;
    end
endmodule
"""

_SV_SHOUTER_EXAMPLE = """\
`timescale 1ns/1ps
module example_usage;
    logic [7:0] in_data, out_data;
    shouter_inv #(.WIDTH(8)) dut(.in_data(in_data), .out_data(out_data));
    initial begin
        in_data = 8'hF0;
        #1;
        $display("out=%h", out_data);
        $finish;
    end
endmodule
"""


def _write_sv_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "rtl-greet-systemverilog")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "rtl-greet-systemverilog", "name": "greet", "version": "1.0.0",
            "domain": "rtl", "tags": ["buffer", "demo", "test"],
        },
        "tech_stack": {"language": "systemverilog", "dependencies": []},
        "description": "Pass-through buffer module.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "src", "greet_buf.sv"), "w") as f:
        f.write(_SV_GREET_SRC)
    with open(os.path.join(wdir, "tests", "test_greet.sv"), "w") as f:
        f.write(_SV_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.sv"), "w") as f:
        f.write(_SV_GREET_EXAMPLE)
    return wdir


def _write_sv_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-shouter-systemverilog")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-systemverilog",
        "name": "shouter",
        "language": "systemverilog",
        "version": "0.1.0",
        "description": "Inverts the buffered output of greet.",
        "tags": ["buffer", "demo", "blueprint"],
        "dependencies": [
            {"id": "rtl-greet-systemverilog", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "src", "shouter_inv.sv"), "w") as f:
        f.write(_SV_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "test_shouter.sv"), "w") as f:
        f.write(_SV_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.sv"), "w") as f:
        f.write(_SV_SHOUTER_EXAMPLE)
    return bp


@pytest.mark.slow
def test_systemverilog_blueprint_validates_end_to_end(carto, project):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("iverilog/vvp not available")
    engine = get_engine("systemverilog")
    if engine is None or not engine.supported:
        pytest.skip("systemverilog engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"systemverilog engine not ready: {msg}")

    _write_sv_widget(str(project))
    bp = _write_sv_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-systemverilog"


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

_GO_GREET_MOD = """\
module greet

go 1.24
"""

_GO_GREET_SRC = """\
// Package greet builds greeting strings.
package greet

// Greeting returns a greeting for name.
func Greeting(name string) string {
	return "hello, " + name
}
"""

_GO_GREET_TEST = """\
package tests

import (
	"testing"

	greet "greet/src"
)

func TestGreeting(t *testing.T) {
	if got := greet.Greeting("test"); got != "hello, test" {
		t.Fatalf("Greeting() = %q", got)
	}
}
"""

_GO_GREET_EXAMPLE = """\
package main

import (
	"fmt"

	greet "greet/src"
)

func main() {
	fmt.Println(greet.Greeting("world"))
}
"""

# The blueprint composes the greet widget. Go's local-module composition
# mechanism is require + replace pointing at the sandbox's cg/ copy.
_GO_SHOUTER_MOD = """\
module shouter

go 1.24

require greet v0.0.0

replace greet => ./cg/infra-greet-go
"""

_GO_SHOUTER_SRC = """\
// Package shouter uppercases greetings from the greet widget.
package shouter

import (
	"strings"

	greet "greet/src"
)

// Shout returns an uppercased greeting for name.
func Shout(name string) string {
	return strings.ToUpper(greet.Greeting(name))
}
"""

_GO_SHOUTER_TEST = """\
package tests

import (
	"testing"

	shouter "shouter/src"
)

func TestShout(t *testing.T) {
	if got := shouter.Shout("test"); got != "HELLO, TEST" {
		t.Fatalf("Shout() = %q", got)
	}
}
"""

_GO_SHOUTER_EXAMPLE = """\
package main

import (
	"fmt"

	shouter "shouter/src"
)

func main() {
	fmt.Println(shouter.Shout("world"))
}
"""


def _write_go_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "infra-greet-go")
    os.makedirs(os.path.join(wdir, "src"))
    os.makedirs(os.path.join(wdir, "tests"))
    os.makedirs(os.path.join(wdir, "examples"))

    manifest = {
        "meta": {
            "id": "infra-greet-go", "name": "greet", "version": "1.0.0",
            "domain": "infra", "tags": ["greeting", "demo", "test"],
        },
        "tech_stack": {"language": "go", "dependencies": []},
        "description": "Builds a greeting string.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "go.mod"), "w") as f:
        f.write(_GO_GREET_MOD)
    with open(os.path.join(wdir, "src", "greet.go"), "w") as f:
        f.write(_GO_GREET_SRC)
    with open(os.path.join(wdir, "tests", "greet_test.go"), "w") as f:
        f.write(_GO_GREET_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.go"), "w") as f:
        f.write(_GO_GREET_EXAMPLE)
    return wdir


def _write_go_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-shouter-go")
    os.makedirs(os.path.join(bp, "src"))
    os.makedirs(os.path.join(bp, "tests"))
    os.makedirs(os.path.join(bp, "examples"))

    manifest = {
        "id": "bp-shouter-go",
        "name": "shouter",
        "language": "go",
        "version": "0.1.0",
        "description": "Uppercases a greeting via the greet widget.",
        "tags": ["greeting", "demo", "blueprint"],
        "dependencies": [
            {"id": "infra-greet-go", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "go.mod"), "w") as f:
        f.write(_GO_SHOUTER_MOD)
    with open(os.path.join(bp, "src", "shouter.go"), "w") as f:
        f.write(_GO_SHOUTER_SRC)
    with open(os.path.join(bp, "tests", "shouter_test.go"), "w") as f:
        f.write(_GO_SHOUTER_TEST)
    with open(os.path.join(bp, "examples", "example_usage.go"), "w") as f:
        f.write(_GO_SHOUTER_EXAMPLE)
    return bp


@pytest.mark.slow
def test_go_blueprint_validates_end_to_end(carto, project):
    if not shutil.which("go"):
        pytest.skip("go not available")
    engine = get_engine("go")
    if engine is None or not engine.supported:
        pytest.skip("go engine not available")
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"go engine not ready: {msg}")

    _write_go_widget(str(project))
    bp = _write_go_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-shouter-go"


# ---------------------------------------------------------------------------
# SPICE
# ---------------------------------------------------------------------------

_SPICE_LOWPASS_SRC = """\
* RC lowpass block
.subckt lowpass in out params: r=1k c=159.155n
R1 in out {r}
C1 out 0 {c}
.ends lowpass
"""

_SPICE_LOWPASS_TEST = """\
.include ../src/lowpass.cir
Vin in 0 AC 1
Xdut in out lowpass r=1k c=159.155n
.control
ac dec 100 10 100k
meas ac fc when vdb(out)=-3
if (fc < 950) | (fc > 1050)
  echo "ASSERT_FAIL cutoff $&fc Hz"
else
  echo "ASSERT_PASS cutoff $&fc Hz"
end
.endc
.end
"""

_SPICE_LOWPASS_EXAMPLE = """\
.include ../src/lowpass.cir
Vin in 0 AC 1
Xf in out lowpass r=1k c=159.155n
.control
ac dec 50 10 100k
meas ac fc when vdb(out)=-3
echo "lowpass fc = $&fc Hz"
.endc
.end
"""

# Blueprint: cascade two lowpass stages from the widget into a steeper filter.
_SPICE_CASCADE_SRC = """\
.include ../cg/analog-lowpass-spice/src/lowpass.cir
.subckt cascade in out params: r=1k c=159.155n
X1 in mid lowpass r={r} c={c}
X2 mid out lowpass r={r} c={c}
.ends cascade
"""

_SPICE_CASCADE_TEST = """\
.include ../src/cascade.cir
Vin in 0 AC 1
Xdut in out cascade r=1k c=159.155n
.control
ac dec 100 10 100k
meas ac att find vdb(out) at=1000
if (att > -6) | (att < -15)
  echo "ASSERT_FAIL cascade attenuation $&att dB at 1kHz"
else
  echo "ASSERT_PASS cascade attenuation $&att dB at 1kHz steeper than one stage"
end
.endc
.end
"""

_SPICE_CASCADE_EXAMPLE = """\
.include ../src/cascade.cir
Vin in 0 AC 1
Xc in out cascade r=1k c=159.155n
.control
ac dec 50 10 100k
meas ac att find vdb(out) at=1000
echo "cascade attenuation at 1kHz = $&att dB"
.endc
.end
"""


def _write_spice_widget(project_dir: str) -> str:
    wdir = os.path.join(project_dir, "cg", "analog-lowpass-spice")
    for d in ("src", "tests", "examples"):
        os.makedirs(os.path.join(wdir, d))
    manifest = {
        "meta": {
            "id": "analog-lowpass-spice", "name": "lowpass", "version": "1.0.0",
            "domain": "analog", "tags": ["filter", "rc", "demo"],
        },
        "tech_stack": {"language": "spice", "dependencies": []},
        "description": "Parametric RC low-pass filter block.",
    }
    with open(os.path.join(wdir, "widget.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(wdir, "src", "lowpass.cir"), "w") as f:
        f.write(_SPICE_LOWPASS_SRC)
    with open(os.path.join(wdir, "tests", "test_lowpass.cir"), "w") as f:
        f.write(_SPICE_LOWPASS_TEST)
    with open(os.path.join(wdir, "examples", "example_usage.cir"), "w") as f:
        f.write(_SPICE_LOWPASS_EXAMPLE)
    return wdir


def _write_spice_blueprint(project_dir: str) -> str:
    bp = os.path.join(project_dir, "cg", "bp-cascade-spice")
    for d in ("src", "tests", "examples"):
        os.makedirs(os.path.join(bp, d))
    manifest = {
        "id": "bp-cascade-spice",
        "name": "cascade",
        "language": "spice",
        "version": "0.1.0",
        "description": "Two-stage RC cascade composing the lowpass block.",
        "tags": ["filter", "cascade", "blueprint"],
        "dependencies": [
            {"id": "analog-lowpass-spice", "version": "1.0.0"},
        ],
        "domains": [],
    }
    with open(os.path.join(bp, "blueprint.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(bp, "src", "cascade.cir"), "w") as f:
        f.write(_SPICE_CASCADE_SRC)
    with open(os.path.join(bp, "tests", "test_cascade.cir"), "w") as f:
        f.write(_SPICE_CASCADE_TEST)
    with open(os.path.join(bp, "examples", "example_usage.cir"), "w") as f:
        f.write(_SPICE_CASCADE_EXAMPLE)
    return bp


@pytest.mark.slow
def test_spice_simulate_captures_control_echo():
    """Windows probe: ngspice's `.control` echo must reach captured output.

    This is the exact failure mode that kept SPICE dormant on Windows - an
    `echo` inside `.control` (how testbenches emit ASSERT_PASS/FAIL) did not
    surface in the captured stdout/stderr pipes there, so the engine never saw
    a sentinel. `_simulate` now also reads ngspice's `-o` log and unions it in,
    which should make sentinel capture platform-independent. Deliberately NOT
    skipped on win32 - this is the guard that tells us Windows is fixed before
    we flip the engine to supported=True.
    """
    if not shutil.which("ngspice"):
        pytest.skip("ngspice not available")
    engine = get_engine("spice")
    if engine is None:
        pytest.skip("spice engine not available")
    netlist = (
        "* echo capture probe\n"
        "V1 in 0 DC 1\n"
        "R1 in 0 1k\n"
        ".control\n"
        "op\n"
        'echo "ASSERT_PASS probe echo captured"\n'
        ".endc\n"
        ".end\n"
    )
    with tempfile.TemporaryDirectory() as d:
        nl = os.path.join(d, "probe.cir")
        with open(nl, "w", encoding="utf-8") as f:
            f.write(netlist)
        ok, output = engine._simulate(nl, cwd=d)
    assert ok, output
    assert "ASSERT_PASS" in output, (
        "ngspice .control echo was not captured - the -o log union should make "
        "this platform-independent. Output:\n" + output
    )


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="SPICE is WIP (supported=False) and not yet validated on Windows - "
           "ngspice's .meas/assert block doesn't emit ASSERT_PASS there. Re-enable "
           "and fix Windows before flipping the engine to supported=True.",
)
def test_spice_blueprint_validates_end_to_end(carto, project, monkeypatch):
    if not shutil.which("ngspice"):
        pytest.skip("ngspice not available")
    engine = get_engine("spice")
    if engine is None:
        pytest.skip("spice engine not available")
    # SPICE ships supported=False until its stress test passes; the blueprint
    # composition itself is testable regardless of the ship gate.
    monkeypatch.setattr(type(engine), "supported", True)
    ok, msg = engine.check_available()
    if not ok:
        pytest.skip(f"spice engine not ready: {msg}")

    _write_spice_widget(str(project))
    bp = _write_spice_blueprint(str(project))

    res = carto.validate_blueprint(bp)
    assert res.get("status") == "success", res
    assert res["id"] == "bp-cascade-spice"
