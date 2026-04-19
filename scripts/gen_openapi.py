#!/usr/bin/env python3
"""Generate the Cartograph cloud-registry OpenAPI 3.1 spec from source.

Walks the @endpoint-decorated functions in cartograph.cloud, introspects the
TypedDict response shapes in cartograph.cloud_schema, hands both to the
dogfooded infra-openapi-generator-python widget, and writes the result to
docs/cloud_api.json (or .yaml if PyYAML is available).

This script is the single source of truth for the wire contract. Adding a
new endpoint = decorate a new function + (optionally) add a new TypedDict.
Re-running this script refreshes the spec. A CI check diffs the committed
spec against a fresh run to catch drift.

Run:
    python scripts/gen_openapi.py

Emit to stdout instead of the file:
    python scripts/gen_openapi.py --stdout
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import sys
import typing
from typing import Any, get_args, get_origin, get_type_hints


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "docs", "cloud_api.json")


def _load_widget(widget_dir: str, module_file: str, loader_name: str):
    """File-path import of a cg/ widget module, bypassing the src/ namespace collision."""
    for base in (
        os.path.join(REPO_ROOT, "cg", widget_dir, "src", module_file),
    ):
        if os.path.isfile(base):
            spec = importlib.util.spec_from_file_location(loader_name, base)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(f"widget module not found: cg/{widget_dir}/src/{module_file}")


# ---------- TypedDict -> JSON Schema ----------

_PRIMITIVES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _is_typeddict(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, dict) and hasattr(tp, "__annotations__") and hasattr(tp, "__total__")


def _schema_for_hint(hint: Any, schema_refs: set[str]) -> dict:
    """Translate a Python type hint into a JSON Schema fragment.

    Collects any referenced TypedDict class names into `schema_refs` so the
    caller can emit them as components.schemas and avoid forward-reference
    breakage.
    """
    if hint is Any:
        return {}
    if hint in _PRIMITIVES:
        return {"type": _PRIMITIVES[hint]}
    if _is_typeddict(hint):
        schema_refs.add(hint.__name__)
        return {"$ref": f"#/components/schemas/{hint.__name__}"}

    origin = get_origin(hint)
    args = get_args(hint)

    if origin in (list, typing.List):
        item = args[0] if args else Any
        return {"type": "array", "items": _schema_for_hint(item, schema_refs)}
    if origin in (dict, typing.Dict):
        value = args[1] if len(args) == 2 else Any
        return {"type": "object", "additionalProperties": _schema_for_hint(value, schema_refs)}
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner = _schema_for_hint(non_none[0], schema_refs)
            return inner  # nullable handled implicitly — TypedDict keys are all optional anyway
        return {"oneOf": [_schema_for_hint(a, schema_refs) for a in non_none]}

    # Fallback: treat unknown as string to avoid emitting broken schema.
    return {"type": "string"}


def _schema_for_typeddict(td: type, schema_refs: set[str]) -> dict:
    """Build a JSON Schema object for a TypedDict class."""
    hints = get_type_hints(td)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field, hint in hints.items():
        properties[field] = _schema_for_hint(hint, schema_refs)
    # TypedDict(total=False) means nothing is required; total=True means all are.
    # Cartograph schemas use total=False uniformly, so required stays empty —
    # registries may omit any field and still be protocol-compatible.
    if getattr(td, "__total__", False):
        required = list(hints.keys())
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _collect_schemas(schema_module) -> dict[str, dict]:
    """Walk a module for TypedDicts, following references transitively."""
    schemas: dict[str, dict] = {}
    refs: set[str] = set()

    # First pass: every TypedDict exported from the module.
    seed: list[type] = []
    for name in dir(schema_module):
        obj = getattr(schema_module, name)
        if _is_typeddict(obj) and obj.__module__ == schema_module.__name__:
            seed.append(obj)

    # Build schemas and discover any referenced names.
    for td in seed:
        schemas[td.__name__] = _schema_for_typeddict(td, refs)

    # Resolve any refs that weren't in the seed set (e.g. nested-only types).
    unresolved = refs - set(schemas.keys())
    for name in unresolved:
        td = getattr(schema_module, name, None)
        if _is_typeddict(td):
            schemas[name] = _schema_for_typeddict(td, refs)
    return schemas


# ---------- main ----------

def build_spec(version: str) -> dict:
    sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
    from cartograph import cloud, cloud_schema  # noqa: E402

    registry_mod = _load_widget("infra_http_endpoint_registry_python",
                                "http_endpoint_registry.py",
                                "_openapi_gen_registry")
    gen_mod = _load_widget("infra_openapi_generator_python",
                           "openapi_generator.py",
                           "_openapi_gen_builder")

    endpoints = registry_mod.get_endpoints(cloud)
    schemas = _collect_schemas(cloud_schema)

    spec = gen_mod.build_openapi(
        endpoints,
        title="Cartograph Cloud Registry",
        version=version,
        description=(
            "Wire protocol for the Cartograph cloud registry. The spec is "
            "generated from the @endpoint-decorated functions in "
            "src/cartograph/cloud.py and the TypedDicts in "
            "src/cartograph/cloud_schema.py — it cannot drift from the "
            "actual client without breaking the generator."
        ),
        servers=[{"url": "https://cartograph.cloud",
                  "description": "Public registry (default)"}],
        schemas=schemas,
    )
    return spec


def _read_client_version() -> str:
    pyproject = os.path.join(REPO_ROOT, "pyproject.toml")
    with open(pyproject) as f:
        for line in f:
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def main():
    ap = argparse.ArgumentParser(description="Generate cloud_api.json from source")
    ap.add_argument("--stdout", action="store_true",
                    help="Emit the spec to stdout instead of writing the file")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help=f"Output path (default: {DEFAULT_OUTPUT})")
    args = ap.parse_args()

    spec = build_spec(version=_read_client_version())
    rendered = json.dumps(spec, indent=2, sort_keys=False) + "\n"

    if args.stdout:
        sys.stdout.write(rendered)
        return
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(rendered)
    print(f"Wrote {args.output} ({len(spec['paths'])} paths, "
          f"{len(spec.get('components', {}).get('schemas', {}))} schemas)")


if __name__ == "__main__":
    main()
