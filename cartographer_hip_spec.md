# Cartographer HIP/C++ Pipeline Spec

**Author:** Claude (consumer/developer perspective)
**Context:** Porting vLLM-Omni to consumer RDNA GPUs (gfx1100, gfx1200). Every kernel fix, build patch, and workaround we create should be captured as a reusable widget so the next person with a Radeon card doesn't start from zero.

---

## 1. New Languages

Cartographer currently supports: python, javascript, typescript, go, rust.

**Add:**

| Language ID | File Extensions | Description |
|------------|----------------|-------------|
| `cpp`      | `.cpp`, `.h`, `.hpp` | Standard C++ (CMake or raw compiler) |
| `hip`      | `.hip`, `.h`, `.hpp` | AMD HIP kernels (compiled with `hipcc`) |
| `c`        | `.c`, `.h` | Plain C (for low-level utilities) |

HIP is a superset of C++ with GPU kernel syntax. Files use `.hip` extension by convention but `hipcc` also accepts `.cpp`. The distinction matters because HIP widgets need GPU-specific build flags and target architectures.

---

## 2. Scaffolding Templates

### `hip` widget scaffold

```
{widget_id}/
  widget.json
  src/
    {name}.hip          # Main kernel source
    {name}.h            # Host-side header (launch wrappers)
  tests/
    test_{name}.py      # Python test harness: compiles, runs, validates
  examples/
    basic_usage.py      # Python: shows how to compile and call the kernel
```

**Why Python tests?** We can't assume a C++ test framework is installed. Python is always available, can shell out to `hipcc`, load the resulting `.so`, and validate output tensors via PyTorch/numpy. This matches how vLLM itself tests its kernels.

### `cpp` widget scaffold

```
{widget_id}/
  widget.json
  src/
    {name}.cpp
    {name}.h
  tests/
    test_{name}.py      # Or test_{name}.cpp with a simple main()
  examples/
    basic_usage.py
```

### `c` widget scaffold

Same as `cpp` but with `.c` extension.

---

## 3. Extended `widget.json` Schema

### New fields in `tech_stack`

```json
{
  "tech_stack": {
    "language": "hip",
    "language_version": "ROCm 6.x+",
    "dependencies": ["hipcc", "rocm-dev"],
    "gpu_targets": ["gfx1100", "gfx1200"],
    "build_cmd": "hipcc -O2 --offload-arch={target} -shared -fPIC src/{name}.hip -o build/{name}.so",
    "compiler": "hipcc"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `gpu_targets` | `string[]` | GPU architecture codes this widget is built/tested for. Examples: `gfx1100`, `gfx1200`, `gfx942`. Used for search filtering. |
| `build_cmd` | `string` | Shell command to build the widget. Supports `{target}` placeholder for multi-arch builds. Optional — if absent, the test harness handles compilation. |
| `compiler` | `string` | Compiler binary name. `hipcc`, `g++`, `clang++`, `gcc`. Informational + used by scaffolding. |

### New field in `meta`

```json
{
  "meta": {
    "widget_type": "kernel"
  }
}
```

| Value | Description |
|-------|-------------|
| `"kernel"` | Standalone GPU kernel (compiled to .so, called from Python/C++) |
| `"patch"` | Modifies an existing codebase (contains diffs or a patch script) |
| `"probe"` | Diagnostic — detects GPU capabilities, reports results |
| `"library"` | Traditional reusable library (default, current behavior) |

This field is **optional** — defaults to `"library"` for backward compatibility. But it lets us search specifically for patches vs kernels vs probes.

---

## 4. Search Filtering

### By GPU target

When I search for `"attention kernel gfx1100"`, Cartographer should:
1. Match on tags/description as it does today
2. **Also** match on `tech_stack.gpu_targets` if the query contains a gfx code

This way: `cartographer_search("rdna attention")` finds widgets tagged with RDNA-related GPU targets.

### By widget type

Allow filtering by the new `widget_type` field:

```
cartographer_search("vllm vmm", type="patch")   # only patch widgets
cartographer_search("warp size", type="probe")   # only diagnostics
```

This could reuse the existing `type` parameter (currently `widget | blueprint | all`) by extending it, or be a separate filter. Up to you on implementation.

---

## 5. Validation Changes

### For `hip` widgets

`cartographer_validate` should:

1. Check that `src/` contains at least one `.hip` or `.cpp` file
2. Check that `tests/` contains test files (`.py` or `.cpp`)
3. **Skip compilation checks** — we can't assume `hipcc` is on the validation machine
4. If tests are Python, run them with `pytest` as usual
5. If `gpu_targets` is specified, just validate it's a non-empty string array

### For `patch` type widgets

1. Check that `src/` contains a `patch.py` or diff files
2. Tests should verify the patch applies cleanly to a mock/fixture

---

## 6. Example Widgets We'll Create

Here's what the first widgets for the vLLM-Omni effort will look like:

### `hip-probe-rdna` (type: probe)
Detects GPU architecture, warp size, VMM support, and available VRAM. Returns a JSON report. Every other widget can depend on this.

### `hip-attention-warp32` (type: kernel)
PagedAttention kernel patched for warp size 32 (RDNA). Drop-in replacement for vLLM's gfx942-optimized version.

### `hip-patch-vllm-novmm` (type: patch)
Disables virtual memory management in vLLM's memory allocator for RDNA GPUs that don't support it. Contains the patch script + verification test.

### `hip-build-rdna-targets` (type: patch)
Build system patch to add gfx1100/gfx1200 to vLLM's CMake configuration. Ensures kernels compile for consumer GPU architectures.

### `hip-fallback-sdpa` (type: library)
Python module that detects when FlashAttention isn't available for the current GPU and routes to PyTorch's native SDPA. Reusable across any project, not just vLLM.

---

## 7. What I Do NOT Need

- **IDE integration** — I work from the terminal
- **Package manager integration** (pip, npm) — HIP widgets aren't pip-installable
- **Cross-compilation** — we compile on the target machine
- **Docker scaffolding** — we run bare metal
- **Complex build systems** — a single `hipcc` command or a short Makefile is enough. No CMake scaffolding needed inside widgets.

---

## 8. Priority Order

If this is too much to do at once, here's what I need first:

1. **`hip` and `cpp` as accepted languages in `cartographer_create`** with the scaffolding templates above
2. **`gpu_targets` field** in widget.json schema (validated but not filtered on yet)
3. **`widget_type` field** in meta (informational, for search later)

Everything else (search filtering, build_cmd, compiler field) is nice-to-have and can come after we start producing widgets.

---

## Summary

Cartographer becomes the knowledge base for "how to run ML inference on consumer AMD GPUs." Every time we fix a kernel, work around a limitation, or discover a compatibility trick, it goes into a widget that anyone can find and install. The HIP/C++ pipeline is what makes that possible.
