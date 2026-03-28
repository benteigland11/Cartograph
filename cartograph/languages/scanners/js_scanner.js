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

    // Risky imports: fs, child_process, net, http, https
    // Check raw line since string content is stripped from code
    const rawTrimmed = line.trim()
    const importPatterns = [
      /require\s*\(\s*['"](\w[\w-]*)['"]/, // require('fs')
      /from\s+['"](\w[\w-]*)['"]/, // import x from 'fs'
      /import\s+['"](\w[\w-]*)['"]/, // import 'fs'
    ]
    const risky = ['fs', 'child_process', 'net', 'http', 'https', 'dgram', 'cluster', 'worker_threads']
    for (const pat of importPatterns) {
      const m = rawTrimmed.match(pat)
      if (m && risky.includes(m[1])) {
        findings.push({
          file: filename, kind: 'risky_import', line: lineNo,
          detail: `import '${m[1]}' - flagged for review`
        })
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
