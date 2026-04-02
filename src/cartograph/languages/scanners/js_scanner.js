/**
 * Cartograph JavaScript/TypeScript source scanner.
 *
 * Scans .js/.jsx/.ts/.tsx files for contamination patterns with awareness
 * of strings, comments, and template literals. Outputs JSON for the Python engine.
 *
 * Usage: node js_scanner.js <file1.js> [file2.ts ...]
 * Output: JSON array of {file, kind, line, detail} objects.
 */

const fs = require('fs')
const path = require('path')

// Node.js built-in modules (skip these for unlisted import checks)
const NODE_BUILTINS = new Set([
  'assert', 'buffer', 'child_process', 'cluster', 'console', 'constants',
  'crypto', 'dgram', 'dns', 'domain', 'events', 'fs', 'http', 'https',
  'module', 'net', 'os', 'path', 'perf_hooks', 'process', 'punycode',
  'querystring', 'readline', 'repl', 'stream', 'string_decoder', 'timers',
  'tls', 'tty', 'url', 'util', 'v8', 'vm', 'worker_threads', 'zlib',
])

// Load declared dependencies from widget.json in cwd
function loadDeclaredDeps() {
  try {
    const data = JSON.parse(fs.readFileSync('widget.json', 'utf-8'))
    const deps = (data.tech_stack || {}).dependencies || []
    return new Set(deps.map(d => {
      // Strip version specifiers: 'react>=18.0.0' -> 'react'
      const bare = d.split(/[><=!~;\[]/)[0].trim().toLowerCase()
      return bare
    }))
  } catch (e) {
    return new Set()
  }
}

const declaredDeps = loadDeclaredDeps()

function scanFile(filename) {
  const findings = []
  const content = fs.readFileSync(filename, 'utf-8')
  const lines = content.split('\n')

  let inBlockComment = false
  let inTemplateLiteral = false

  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1
    let line = lines[i]
    let code = ''

    // Process character by character to handle strings/comments
    let inString = false
    let stringChar = ''
    let escaped = false

    for (let j = 0; j < line.length; j++) {
      const ch = line[j]
      const next = j + 1 < line.length ? line[j + 1] : ''

      if (escaped) {
        escaped = false
        if (inString || inTemplateLiteral) continue
        code += ch
        continue
      }

      if (ch === '\\') {
        escaped = true
        if (inString || inTemplateLiteral) continue
        code += ch
        continue
      }

      // Block comment
      if (inBlockComment) {
        if (ch === '*' && next === '/') {
          inBlockComment = false
          j++ // skip the /
        }
        continue
      }

      // Template literal
      if (inTemplateLiteral) {
        if (ch === '`') {
          inTemplateLiteral = false
        }
        continue
      }

      // String literal
      if (inString) {
        if (ch === stringChar) {
          inString = false
        }
        continue
      }

      // Start of block comment
      if (ch === '/' && next === '*') {
        inBlockComment = true
        j++
        continue
      }

      // Line comment
      if (ch === '/' && next === '/') {
        break // rest of line is comment
      }

      // Start of string
      if (ch === '"' || ch === "'") {
        inString = true
        stringChar = ch
        continue
      }

      // Start of template literal
      if (ch === '`') {
        inTemplateLiteral = true
        continue
      }

      code += ch
    }

    code = code.trim()
    if (!code) continue

    // --- Checks ---

    // console.log / console.warn / console.error / console.debug
    const consoleMatch = code.match(/\bconsole\s*\.\s*(log|warn|error|debug|info|trace)\s*\(/)
    if (consoleMatch) {
      findings.push({
        file: filename, kind: 'console_log', line: lineNo,
        detail: `console.${consoleMatch[1]}() call - remove debug output from src/`
      })
    }

    // process.exit()
    if (/\bprocess\s*\.\s*exit\s*\(/.test(code)) {
      findings.push({
        file: filename, kind: 'process_exit', line: lineNo,
        detail: 'process.exit() call - widgets must not exit the process'
      })
    }

    // Import checks: risky imports (error) + unlisted imports (warning)
    // Check raw line since string content is stripped from code
    const rawTrimmed = line.trim()
    const importPatterns = [
      /require\s*\(\s*['"]([^'"./][^'"]*)['"]/, // require('foo') - skip relative
      /from\s+['"]([^'"./][^'"]*)['"]/, // import x from 'foo'
      /import\s+['"]([^'"./][^'"]*)['"]/, // import 'foo'
    ]
    const risky = ['fs', 'child_process', 'net', 'http', 'https', 'dgram', 'cluster', 'worker_threads']
    for (const pat of importPatterns) {
      const m = rawTrimmed.match(pat)
      if (m) {
        // Get bare package name (handle scoped: @scope/pkg -> @scope/pkg)
        const fullImport = m[1]
        const bare = fullImport.startsWith('@')
          ? fullImport.split('/').slice(0, 2).join('/')
          : fullImport.split('/')[0]
        const bareLower = bare.toLowerCase()

        if (risky.includes(bareLower)) {
          findings.push({
            file: filename, kind: 'risky_import', line: lineNo,
            detail: `import '${bare}' - flagged for review`
          })
        }

        // Unlisted import check (warning) - skip builtins
        if (!NODE_BUILTINS.has(bareLower) && !declaredDeps.has(bareLower)) {
          findings.push({
            file: filename, kind: 'unlisted_import', line: lineNo,
            detail: `import '${bare}' - not in widget.json dependencies`,
            severity: 'warning'
          })
        }

        break
      }
    }

    // eval()
    if (/\beval\s*\(/.test(code)) {
      findings.push({
        file: filename, kind: 'eval', line: lineNo,
        detail: 'eval() call - dynamic code execution is a security risk'
      })
    }

    // --- Warning-level checks (contamination) ---

    // Absolute paths in strings (block)
    const absPathMatch = rawTrimmed.match(/['"](?:\/home\/|\/Users\/|\/root\/|[A-Za-z]:[/\\])[^'"]{3,}['"]/)
    if (absPathMatch) {
      findings.push({
        file: filename, kind: 'abs_path', line: lineNo,
        detail: `absolute path ${absPathMatch[0]} - widgets must be portable`,
        severity: 'block'
      })
    }

    // Credentials (block in src, warning in tests)
    const credMatch = rawTrimmed.match(/(?:api_key|api_secret|secret_key|access_token|auth_token|password|passwd|credential)\s*=\s*['"][^'"]{6,}['"]/i)
    if (credMatch) {
      const inTests = filename.includes('/tests/') || filename.includes('\\tests\\')
      findings.push({
        file: filename, kind: 'credential', line: lineNo,
        detail: inTests
          ? `possible credential in test - verify it's fake: ${credMatch[0].substring(0, 40)}`
          : `possible credential assignment - ${credMatch[0].substring(0, 40)}`,
        severity: inTests ? 'warning' : 'block'
      })
    }

    // Hardcoded URLs (block)
    const urlMatch = rawTrimmed.match(/['"]https?:\/\/(?!(?:localhost|127\.0\.0\.1|[\w-]*\.?example\.com|schemas?\.))[^'"]{8,}['"]/)
    if (urlMatch) {
      findings.push({
        file: filename, kind: 'hardcoded_url', line: lineNo,
        detail: `hardcoded URL ${urlMatch[0].substring(0, 60)}`,
        severity: 'block'
      })
    }

    // Hardcoded IPs (block)
    const ipMatch = rawTrimmed.match(/['"](?:\d{1,3}\.){3}\d{1,3}(?::\d+)?['"]/)
    if (ipMatch) {
      findings.push({
        file: filename, kind: 'hardcoded_ip', line: lineNo,
        detail: `hardcoded IP ${ipMatch[0]}`,
        severity: 'block'
      })
    }

    // process.env access
    if (/\bprocess\s*\.\s*env\b/.test(code)) {
      findings.push({
        file: filename, kind: 'env_var', line: lineNo,
        detail: 'process.env access - verify it is not project-specific',
        severity: 'warning'
      })
    }

    // Hardcoded values: const/let with literal numbers or strings
    const constMatch = code.match(/\b(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(.+)/)
    if (constMatch) {
      const varName = constMatch[1]
      const valPart = constMatch[2].trim().replace(/;$/, '').trim()
      // Numeric literal
      if (/^-?\d+\.?\d*(?:e[+-]?\d+)?$/.test(valPart)) {
        findings.push({
          file: filename, kind: 'hardcoded_value', line: lineNo,
          detail: `${varName} = ${valPart} - consider making this a parameter`,
          severity: 'warning'
        })
      }
      // String literal (from raw line since strings are stripped from code)
      const rawValMatch = rawTrimmed.match(/\b(?:const|let)\s+\w+\s*=\s*(['"])(.+)\1/)
      if (rawValMatch && rawValMatch[2].length > 0) {
        findings.push({
          file: filename, kind: 'hardcoded_value', line: lineNo,
          detail: `${varName} = "${rawValMatch[2].substring(0, 60)}" - consider making this a parameter`,
          severity: 'warning'
        })
      }
    }

  }

  return findings
}

// --- Main ---
if (process.argv.length < 3) {
  console.log(JSON.stringify({ error: 'usage: node js_scanner.js <file1> [file2 ...]' }))
  process.exit(1)
}

const allFindings = []
for (let i = 2; i < process.argv.length; i++) {
  const filename = process.argv[i]
  if (!fs.existsSync(filename)) {
    allFindings.push({ file: filename, kind: 'error', line: 0, detail: 'file not found' })
    continue
  }
  allFindings.push(...scanFile(filename))
}

console.log(JSON.stringify(allFindings))
