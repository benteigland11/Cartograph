## Cartograph Nim source scanner.
##
## Scans .nim files for contamination patterns with awareness of strings,
## comments, and multiline constructs. Outputs JSON for the Python engine.
##
## Usage: nim r nim_scanner.nim <file1.nim> [file2.nim ...]
## Output: JSON array of {file, kind, line, detail} objects.

import std/[json, os, strutils, sets]

type
  Finding = object
    file: string
    kind: string
    line: int
    detail: string
    severity: string  # "error" or "warning"

# Nim stdlib modules - skip for unlisted import checks
const nimStdlib = [
  "std/algorithm", "std/atomics", "std/base64", "std/bitops", "std/browsers",
  "std/cgi", "std/colors", "std/complex", "std/critbits", "std/db_common",
  "std/db_mysql", "std/db_postgres", "std/db_sqlite", "std/deques",
  "std/distros", "std/dynlib", "std/encodings", "std/enumerate",
  "std/envvars", "std/exitprocs", "std/files", "std/formatfloat",
  "std/hashes", "std/heapqueue", "std/htmlgen", "std/htmlparser",
  "std/httpclient", "std/httpcore", "std/intsets", "std/json", "std/jsonutils",
  "std/locks", "std/logging", "std/macros", "std/marshal", "std/math",
  "std/md5", "std/memfiles", "std/mimetypes", "std/monotimes", "std/net",
  "std/nativesockets", "std/oids", "std/options", "std/os", "std/osproc",
  "std/parsecfg", "std/parsecsv", "std/parsejson", "std/parseopt",
  "std/parsesql", "std/parseutils", "std/parsexml", "std/paths", "std/pathnorm",
  "std/pegs", "std/posix", "std/random", "std/rationals", "std/re",
  "std/readline", "std/rlocks", "std/ropes", "std/selectors", "std/sequtils",
  "std/sets", "std/sha1", "std/sharedlist", "std/sharedtables",
  "std/smtp", "std/sockets", "std/stats", "std/streams", "std/streamwrapper",
  "std/strformat", "std/strscans", "std/strtabs", "std/strutils",
  "std/sugar", "std/sysrand", "std/tables", "std/tempfiles", "std/terminal",
  "std/threadpool", "std/times", "std/typeinfo", "std/typetraits",
  "std/unicode", "std/unittest", "std/uri", "std/volatile", "std/widestrs",
  "std/winlean", "std/wordwrap", "std/wrapnils", "std/xmlparser",
  "std/xmltree",
  # Short forms (without std/ prefix)
  "algorithm", "atomics", "base64", "bitops", "browsers", "cgi", "colors",
  "complex", "critbits", "deques", "distros", "dynlib", "encodings",
  "enumerate", "envvars", "exitprocs", "files", "formatfloat", "hashes",
  "heapqueue", "htmlgen", "htmlparser", "httpclient", "httpcore", "intsets",
  "json", "jsonutils", "locks", "logging", "macros", "marshal", "math",
  "md5", "memfiles", "mimetypes", "monotimes", "net", "nativesockets",
  "oids", "options", "os", "osproc", "parsecfg", "parsecsv", "parsejson",
  "parseopt", "parsesql", "parseutils", "parsexml", "paths", "pathnorm",
  "pegs", "posix", "random", "rationals", "re", "readline", "rlocks",
  "ropes", "selectors", "sequtils", "sets", "sha1", "sharedlist",
  "sharedtables", "smtp", "sockets", "stats", "streams", "streamwrapper",
  "strformat", "strscans", "strtabs", "strutils", "sugar", "sysrand",
  "tables", "tempfiles", "terminal", "threadpool", "times", "typeinfo",
  "typetraits", "unicode", "unittest", "uri", "volatile", "widestrs",
  "winlean", "wordwrap", "wrapnils", "xmlparser", "xmltree",
  # system is always available
  "system",
].toHashSet()

proc loadDeclaredDeps(): HashSet[string] =
  ## Read widget.json from cwd and extract dependency names.
  result = initHashSet[string]()
  try:
    let data = parseJson(readFile("widget.json"))
    let deps = data{"tech_stack", "dependencies"}
    if deps != nil and deps.kind == JArray:
      for dep in deps:
        if dep.kind == JString:
          # Strip version specifiers: "nimble_pkg>=1.0" -> "nimble_pkg"
          var bare = dep.getStr()
          for i, c in bare:
            if c in {' ', '>', '<', '=', '!', '~', ';', '['}:
              bare = bare[0 ..< i]
              break
          result.incl(bare.strip().toLower())
  except:
    discard

let declaredDeps = loadDeclaredDeps()

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
  var topLevelSection = true

  for i, rawLine in lines:
    let lineNo = i + 1
    let stripped = rawLine.strip()
    let inTests = "/tests/" in filename or "\\tests\\" in filename
    let inExamples = "/examples/" in filename or "\\examples\\" in filename

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

    let startsIndented = rawLine.len > 0 and rawLine[0].isSpaceAscii()
    if not startsIndented and not code.startsWith("import ") and not code.startsWith("from "):
      topLevelSection = true

    # --- Checks ---

    # echo detection
    if code.startsWith("echo ") or code.startsWith("echo(") or code == "echo":
      result.add(Finding(
        file: filename, kind: "echo", line: lineNo,
        detail: "echo call - remove debug output from src/",
        severity: "error"))

    # quit detection
    if code.startsWith("quit") and (code.len == 4 or code[4] in {'(', ' '}):
      result.add(Finding(
        file: filename, kind: "quit", line: lineNo,
        detail: "quit() call - widgets must not exit the process",
        severity: "error"))

    if "system.quit" in code:
      result.add(Finding(
        file: filename, kind: "quit", line: lineNo,
        detail: "system.quit() call - widgets must not exit the process",
        severity: "error"))

    # C FFI pragmas
    if "{.importc" in code:
      result.add(Finding(
        file: filename, kind: "ffi", line: lineNo,
        detail: "{.importc.} - C FFI makes widgets platform-dependent",
        severity: "error"))

    if "{.compile" in code:
      result.add(Finding(
        file: filename, kind: "ffi", line: lineNo,
        detail: "{.compile.} - C FFI makes widgets platform-dependent",
        severity: "error"))

    # Global mutable state
    if "{.global.}" in code:
      result.add(Finding(
        file: filename, kind: "global", line: lineNo,
        detail: "{.global.} - widgets must not use global mutable state",
        severity: "error"))

    # isMainModule guard
    if "when isMainModule" in code:
      result.add(Finding(
        file: filename, kind: "main_module", line: lineNo,
        detail: "when isMainModule - widgets are libraries, not executables",
        severity: "error"))

    # OS-specific when defined()
    const osTargets = ["windows", "linux", "macosx", "osx", "posix",
                       "unix", "freebsd", "netbsd", "openbsd", "haiku",
                       "android", "ios"]
    if "when defined(" in code.toLower():
      for target in osTargets:
        if ("defined(" & target) in code.toLower():
          result.add(Finding(
            file: filename, kind: "os_specific", line: lineNo,
            detail: "OS-specific when defined(" & target & ") - widgets must validate on all platforms",
            severity: "error"))
          break

    # Import checks: risky imports (error) + unlisted imports (warning)
    if code.startsWith("import ") or code.startsWith("from "):
      let lower = code.toLower()
      const riskyModules = ["std/os", "std/osproc", "std/httpclient",
                            "std/net", "std/nativesockets"]
      for m in riskyModules:
        if m in lower:
          result.add(Finding(
            file: filename, kind: "risky_import", line: lineNo,
            detail: "import " & m & " - flagged for review",
            severity: "error"))

      # Unlisted import check - extract module name(s)
      var importLine = code
      if importLine.startsWith("from "):
        # "from module import thing" -> check "module"
        importLine = importLine[5 .. ^1].strip()
        let spacePos = importLine.find(" ")
        if spacePos > 0:
          importLine = importLine[0 ..< spacePos]
      elif importLine.startsWith("import "):
        importLine = importLine[7 .. ^1].strip()

      # Handle comma-separated imports: "import a, b, c"
      let modules = importLine.split(",")
      for rawMod in modules:
        let modName = rawMod.strip().split("/")[^1].strip()  # std/foo -> foo
        let fullMod = rawMod.strip().toLower()
        if rawMod.strip().len > 0 and "/" notin rawMod and modName.toLower() in nimStdlib and modName.toLower() != "system":
          result.add(Finding(
            file: filename, kind: "std_import_style", line: lineNo,
            detail: "import " & modName & " - prefer std/" & modName,
            severity: "warning"))
        if modName.len > 0 and fullMod notin nimStdlib and modName.toLower() notin nimStdlib:
          if modName.toLower() notin declaredDeps:
            result.add(Finding(
              file: filename, kind: "unlisted_import", line: lineNo,
              detail: "import " & modName & " - not in widget.json dependencies",
              severity: "warning"))

    # Sleep/blocking: sleep(), sleepAsync()
    # In src/: block. In tests/examples: warn if duration > 1000.
    if code.startsWith("sleep") and (code.len == 5 or code[5] in {'(', ' '}):
      if not inTests and not inExamples:
        result.add(Finding(
          file: filename, kind: "sleep", line: lineNo,
          detail: "sleep() call - widgets must not block the caller",
          severity: "block"))
      else:
        # Check for large duration: sleep(2000)
        let parenPos = code.find("(")
        if parenPos >= 0:
          let afterParen = code[parenPos + 1 .. ^1].strip()
          let endPos = afterParen.find(")")
          if endPos > 0:
            let durStr = afterParen[0 ..< endPos].strip()
            try:
              let dur = parseInt(durStr)
              if dur > 1000:
                result.add(Finding(
                  file: filename, kind: "sleep", line: lineNo,
                  detail: "sleep(" & durStr & ") - consider reducing sleep duration",
                  severity: "warning"))
            except CatchableError:
              discard

    if "sleepAsync" in code:
      if not inTests and not inExamples:
        result.add(Finding(
          file: filename, kind: "sleep", line: lineNo,
          detail: "sleepAsync() call - widgets must not block the caller",
          severity: "block"))

    if "os.sleep" in code.toLower():
      if not inTests and not inExamples:
        result.add(Finding(
          file: filename, kind: "sleep", line: lineNo,
          detail: "os.sleep() call - widgets must not block the caller",
          severity: "block"))

    # --- Warning/block-level checks (contamination) ---

    # Absolute paths in strings (block)
    if "\"/" in rawLine or "\"C:" in rawLine or "\"c:" in rawLine:
      if rawLine.contains("\"/home/") or rawLine.contains("\"/Users/") or
         rawLine.contains("\"/root/") or rawLine.contains("\"C:") or
         rawLine.contains("\"c:"):
        result.add(Finding(
          file: filename, kind: "abs_path", line: lineNo,
          detail: "absolute path in string - widgets must be portable",
          severity: "block"))

    # Credentials (block in src, warning in tests)
    let lowerRaw = rawLine.toLower()
    if ("api_key" in lowerRaw or "secret_key" in lowerRaw or
        "access_token" in lowerRaw or "auth_token" in lowerRaw or
        "password" in lowerRaw or "credential" in lowerRaw) and
       "= \"" in rawLine and rawLine.count("\"") >= 2:
      result.add(Finding(
        file: filename, kind: "credential", line: lineNo,
        detail: if inTests: "possible credential in test - verify it's fake"
                else: "possible credential assignment",
        severity: if inTests: "warning" else: "block"))

    # Hardcoded URLs (warning)
    if "\"http://" in rawLine or "\"https://" in rawLine:
      if not ("localhost" in rawLine or "127.0.0.1" in rawLine or
              "example.com" in rawLine or ".test/" in rawLine or
              ".test\"" in rawLine or ".test:" in rawLine):
        result.add(Finding(
          file: filename, kind: "hardcoded_url", line: lineNo,
          detail: "hardcoded URL in string",
          severity: "warning"))

    # Hardcoded IPs (block) - string scan for "N.N.N.N" pattern
    block ipCheck:
      let qpos = rawLine.find('"')
      if qpos < 0: break ipCheck
      let after = rawLine[qpos + 1 .. ^1]
      var dots = 0
      var digits = 0
      var valid = false
      for ci in 0 ..< after.len:
        let c = after[ci]
        if c == '"':
          if dots == 3 and digits > 0:
            valid = true
          break
        elif c == '.':
          if digits == 0: break ipCheck
          dots += 1
          digits = 0
          if dots > 3: break ipCheck
        elif c.isDigit:
          digits += 1
          if digits > 3: break ipCheck
        elif c == ':' and dots == 3 and digits > 0:
          # port suffix like "10.0.0.1:8080" - keep scanning
          valid = true
          break
        else:
          break ipCheck
      if valid or (dots == 3 and digits > 0):
        result.add(Finding(
          file: filename, kind: "hardcoded_ip", line: lineNo,
          detail: "hardcoded IP address in string",
          severity: if inTests: "warning" else: "block"))

    # Environment variable access
    if "getenv(" in code.toLower() or "getEnv(" in code or "envPairs" in code:
      result.add(Finding(
        file: filename, kind: "env_var", line: lineNo,
        detail: "environment variable access - verify it is not project-specific",
        severity: "warning"))

    # Hardcoded values: let/const with numeric literals
    if code.startsWith("let ") or code.startsWith("const "):
      let eqPos = code.find(" = ")
      if eqPos >= 0:
        let afterKeyword = code.split(" ", 1)[1].strip()
        let nameEnd = afterKeyword.find(" ")
        if nameEnd > 0:
          let varName = afterKeyword[0 ..< nameEnd].strip(chars = {':', '*'})
          let valPart = code[eqPos + 3 .. ^1].strip()
          if varName.len > 0 and valPart.len > 0:
            var checkVal = valPart
            if checkVal.startsWith("-"):
              checkVal = checkVal[1 .. ^1]
            if checkVal.len > 0 and (checkVal[0].isDigit or checkVal[0] == '.'):
              var allNumChars = true
              for c in checkVal:
                if c notin {'0'..'9', '.', '-', 'e', 'E', '+', '_', '\''}:
                  allNumChars = false
                  break
              if allNumChars:
                result.add(Finding(
                  file: filename, kind: "hardcoded_value", line: lineNo,
                  detail: varName & " = " & valPart & " - consider making this a parameter",
                  severity: "warning"))
            # String literal
            elif valPart.startsWith("\"") and valPart.endsWith("\"") and valPart.len > 2:
              let strVal = valPart[1 ..< valPart.len - 1]
              result.add(Finding(
                file: filename, kind: "hardcoded_value", line: lineNo,
                detail: varName & " = \"" & strVal[0 ..< min(strVal.len, 60)] & "\" - consider making this a parameter",
                severity: "warning"))

    if topLevelSection and code.startsWith("var ") and "{.global.}" notin code:
      let afterKeyword = code[4 .. ^1].strip()
      let splitters = [' ', ':', '=', '*']
      var endPos = afterKeyword.len
      for idx, ch in afterKeyword:
        if ch in splitters:
          endPos = idx
          break
      let varName = afterKeyword[0 ..< endPos].strip()
      if varName.len > 0:
        result.add(Finding(
          file: filename, kind: "top_level_var", line: lineNo,
          detail: "var " & varName & " - avoid top-level mutable state in widgets",
          severity: "warning"))

    if not startsIndented and (code.startsWith("proc ") or code.startsWith("func ") or
                               code.startsWith("template ") or code.startsWith("macro ") or
                               code.startsWith("iterator ") or code.startsWith("converter ") or
                               code.startsWith("method ") or code.startsWith("type ") or
                               code.startsWith("var ") or code.startsWith("let ") or
                               code.startsWith("const ")):
      topLevelSection = false


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
        "detail": f.detail,
        "severity": f.severity
      })

  echo $allFindings
