## Cartograph Nim source scanner.
##
## Scans .nim files for contamination patterns with awareness of strings,
## comments, and multiline constructs. Outputs JSON for the Python engine.
##
## Usage: nim r nim_scanner.nim <file1.nim> [file2.nim ...]
## Output: JSON array of {file, kind, line, detail} objects.

import std/[json, os, strutils, re]

type
  Finding = object
    file: string
    kind: string
    line: int
    detail: string

proc isInCode(line: string): bool =
  ## Returns false if the line is a comment-only line.
  let stripped = line.strip()
  return stripped.len > 0 and not stripped.startsWith("#") and not stripped.startsWith("##")

proc scanFile(filename: string): seq[Finding] =
  result = @[]
  let content = readFile(filename)
  let lines = content.splitLines()

  var inMultilineString = false
  var inRawString = false

  for i, rawLine in lines:
    let lineNo = i + 1
    let stripped = rawLine.strip()

    # Track multiline string literals (triple quotes)
    if inMultilineString:
      if "\"\"\"" in stripped:
        inMultilineString = false
      continue

    # Skip empty lines and pure comments
    if stripped.len == 0 or stripped.startsWith("#"):
      continue

    # Check for multiline string start (but not end on same line)
    let tripleCount = stripped.count("\"\"\"")
    if tripleCount == 1:
      # Opens a multiline string, skip until close
      inMultilineString = true
      # Still check the code portion before the triple quote
      let beforeTriple = rawLine.split("\"\"\"")[0]
      if beforeTriple.strip().len == 0:
        continue

    # Strip inline comments (naive but handles common case)
    var code = stripped
    let hashPos = code.find(" #")
    if hashPos >= 0:
      # Make sure it's not inside a string
      var inStr = false
      var escaped = false
      for ci in 0 ..< hashPos:
        if escaped:
          escaped = false
          continue
        if code[ci] == '\\':
          escaped = true
          continue
        if code[ci] == '"':
          inStr = not inStr
      if not inStr:
        code = code[0 ..< hashPos].strip()

    if code.len == 0:
      continue

    # --- Checks ---

    # echo detection
    if code.startsWith("echo ") or code.startsWith("echo(") or code == "echo":
      result.add(Finding(
        file: filename, kind: "echo", line: lineNo,
        detail: "echo call - remove debug output from src/"))

    # quit detection
    if code.startsWith("quit") and (code.len == 4 or code[4] in {'(', ' '}):
      result.add(Finding(
        file: filename, kind: "quit", line: lineNo,
        detail: "quit() call - widgets must not exit the process"))

    if "system.quit" in code:
      result.add(Finding(
        file: filename, kind: "quit", line: lineNo,
        detail: "system.quit() call - widgets must not exit the process"))

    # C FFI pragmas
    if "{.importc" in code:
      result.add(Finding(
        file: filename, kind: "ffi", line: lineNo,
        detail: "{.importc.} - C FFI makes widgets platform-dependent"))

    if "{.compile" in code:
      result.add(Finding(
        file: filename, kind: "ffi", line: lineNo,
        detail: "{.compile.} - C FFI makes widgets platform-dependent"))

    # Global mutable state
    if "{.global.}" in code:
      result.add(Finding(
        file: filename, kind: "global", line: lineNo,
        detail: "{.global.} - widgets must not use global mutable state"))

    # isMainModule guard
    if "when isMainModule" in code:
      result.add(Finding(
        file: filename, kind: "main_module", line: lineNo,
        detail: "when isMainModule - widgets are libraries, not executables"))

    # OS-specific when defined()
    const osTargets = ["windows", "linux", "macosx", "osx", "posix",
                       "unix", "freebsd", "netbsd", "openbsd", "haiku",
                       "android", "ios"]
    if "when defined(" in code.toLower():
      for target in osTargets:
        if ("defined(" & target) in code.toLower():
          result.add(Finding(
            file: filename, kind: "os_specific", line: lineNo,
            detail: "OS-specific when defined(" & target & ") - widgets must validate on all platforms"))
          break

    # Risky stdlib imports (future domain restrictions)
    if code.startsWith("import ") or code.startsWith("from "):
      let lower = code.toLower()
      const riskyModules = ["std/os", "std/osproc", "std/httpclient",
                            "std/net", "std/nativesockets"]
      for m in riskyModules:
        if m in lower:
          result.add(Finding(
            file: filename, kind: "risky_import", line: lineNo,
            detail: "import " & m & " - flagged for review"))


when isMainModule:
  if paramCount() < 1:
    echo """{"error": "usage: nim r nim_scanner.nim <file1.nim> [file2.nim ...]"}"""
    quit(1)

  var allFindings = newJArray()
  for i in 1 .. paramCount():
    let filename = paramStr(i)
    if not fileExists(filename):
      allFindings.add(%*{"file": filename, "kind": "error", "line": 0,
                         "detail": "file not found"})
      continue
    let findings = scanFile(filename)
    for f in findings:
      allFindings.add(%*{
        "file": f.file,
        "kind": f.kind,
        "line": f.line,
        "detail": f.detail
      })

  echo $allFindings
