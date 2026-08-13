/**
 * 安全扫描脚本（security-audit 技能配套）
 *
 * 静态扫描代码中的敏感信息泄露风险，输出分级报告：
 *   🔴 HIGH   —— 真实密钥/私钥，需立即处理
 *   🟠 MEDIUM —— 敏感命名硬编码，需人工确认
 *   🟡 INFO   —— 占位符/测试值，通常安全
 *
 * 用法：
 *   node scripts/security-scan.js                # 扫描全项目
 *   node scripts/security-scan.js src/electron   # 指定目录/文件
 *
 * 说明：
 *   - 报告中的密钥值一律脱敏（仅显示前 8 字符）
 *   - 语义类风险（SQL 注入、IPC 暴露、Electron 配置）由技能执行时人工审查
 *   - 退出码：1 = 发现 HIGH/MEDIUM 级风险（供 CI/hook 检测）
 */
import fs from 'node:fs'
import path from 'node:path'

/** 排除的目录与文件 */
const EXCLUDE_DIRS = new Set([
  'node_modules', 'dist', 'dist-electron', 'coverage', 'release', '.git', '.claude', '.vite',
  '.venv', 'data', // LangChainRAG:Python 虚拟环境与运行时数据
])
// .env 含真实密钥但已被 .gitignore 排除(不会进仓库),扫描器不审计,避免误报
const EXCLUDE_FILES = new Set(['package-lock.json', 'security-scan.js', '.env'])
/** 参与扫描的文件扩展名 */
const SUPPORTED_EXT = new Set(['.ts', '.tsx', '.js', '.jsx', '.vue', '.json', '.env', '.yml', '.yaml', '.cjs', '.mjs', '.py'])
/** 敏感命名关键字（赋值名） */
const SENSITIVE_KEYWORD = /(?:passw(?:or)?d|pwd|secret|token|api[_-]?key|apikey|private[_-]?key|access[_-]?key|client[_-]?secret|auth[_-]?key|bearer)/i

/** 高熵判断：长度 ≥ 16 且混合大小写字母与数字（或纯 base64/hex 特征） */
function isHighEntropy(value) {
  if (value.length < 16) return false
  const hasUpper = /[A-Z]/.test(value)
  const hasLower = /[a-z]/.test(value)
  const hasDigit = /\d/.test(value)
  const isBase64ish = /^[A-Za-z0-9+/=_-]+$/.test(value)
  return isBase64ish && hasUpper && hasLower && hasDigit
}

/** 占位符/测试值判断 */
const PLACEHOLDER = /^(test|example|your[-_]?|xxx+|demo|dummy|placeholder|changeme|123+$|password$|passwd$|secret$|token$|api[_-]?key$|null$|undefined$|true$|false$)/i

/** 从一行中提取赋值/冒号后的字符串字面量（支持 ' " ` 与无引号） */
function extractValue(line) {
  const m = line.match(/[=:]\s*['"]?([^'"\s,;]+)['"]?$/)
  return m ? m[1].replace(/[;,]$/, '') : null
}

/** 各规则定义：name + 测试函数（返回 {level, type, value} 或 null） */
const RULES = [
  {
    name: '私钥块',
    test: line => {
      if (/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(line)) {
        return { level: 'HIGH', type: '私钥块' }
      }
      return null
    },
  },
  {
    name: 'JWT 令牌',
    test: line => {
      const m = line.match(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}/)
      if (m) return { level: 'HIGH', type: 'JWT 令牌' }
      return null
    },
  },
  {
    name: '云厂商密钥',
    test: line => {
      const m = line.match(/\b(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b/)
      if (m) return { level: 'HIGH', type: '云/平台密钥' }
      return null
    },
  },
  {
    name: '敏感命名赋值',
    test: line => {
      if (!SENSITIVE_KEYWORD.test(line)) return null
      // 排除注释行与 import/require
      const trimmed = line.trim()
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('#')) return null
      if (/^(import|export|from|require\(|include)/.test(trimmed)) return null

      const value = extractValue(line)
      if (!value) return null
      if (value.length < 4) return null
      // 值含 点/括号/下标/引号函数调用 = 代码引用(如 body.refresh_token、resp.data.token、
      // localStorage.getItem('token')、settings.jwt_secret),非硬编码字面量,跳过
      if (/[().[\]'"]/.test(value)) return null

      if (PLACEHOLDER.test(value)) return { level: 'INFO', type: '敏感命名赋值（疑似占位/测试值）' }
      if (isHighEntropy(value)) return { level: 'HIGH', type: '敏感命名赋值（高熵值）' }
      return { level: 'MEDIUM', type: '敏感命名赋值' }
    },
  },
  {
    name: '高熵长串（独立行）',
    test: line => {
      const trimmed = line.trim()
      if (trimmed.startsWith('//') || trimmed.startsWith('*')) return null
      const m = line.match(/([A-Za-z0-9+/=_-]{40,})/)
      if (!m) return null
      const value = m[1]
      if (PLACEHOLDER.test(value) || value.includes('example') || value.includes('test')) return null
      if (isHighEntropy(value)) return { level: 'MEDIUM', type: '高熵长串（疑似密钥）' }
      return null
    },
  },
]

/** 递归收集受支持文件（相对路径） */
function collectFiles(dir, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry.name)) continue
      collectFiles(path.join(dir, entry.name), results)
    } else if (SUPPORTED_EXT.has(path.extname(entry.name)) && !EXCLUDE_FILES.has(entry.name)) {
      results.push(path.join(dir, entry.name))
    }
  }
  return results
}

/** 解析扫描目标 */
function resolveTargets(args) {
  if (args.length === 0) return collectFiles(process.cwd())
  const files = []
  for (const arg of args) {
    const abs = path.resolve(arg)
    const stat = fs.statSync(abs)
    if (stat.isDirectory()) collectFiles(abs, files)
    else files.push(abs)
  }
  return files
}

/** 脱敏：只保留前 8 字符 */
function mask(value) {
  if (!value) return ''
  return value.length <= 8 ? value : value.slice(0, 8) + '…(长度 ' + value.length + ')'
}

/**
 * 人工确认豁免清单：scripts/security-allowlist.json
 * 元素格式 "相对路径:行号"（如 "backend/app/core/config.py:49"）。
 * 由安全审计人工确认"该处为默认值/测试值/误报"后加入；新出现未豁免的命中仍会报告。
 * 文件不存在或损坏时视为无豁免（不弱化门禁）。
 */
const ALLOWLIST_PATH = path.join(process.cwd(), 'scripts', 'security-allowlist.json')
function loadAllowlist() {
  try {
    const raw = JSON.parse(fs.readFileSync(ALLOWLIST_PATH, 'utf8'))
    return new Set(Array.isArray(raw) ? raw : [])
  } catch {
    return new Set()
  }
}

/** 扫描单个文件，返回命中列表 */
function scanFile(file) {
  const source = fs.readFileSync(file, 'utf-8')
  const findings = []
  source.split('\n').forEach((line, index) => {
    for (const rule of RULES) {
      const hit = rule.test(line)
      if (hit) {
        findings.push({ ...hit, file: path.relative(process.cwd(), file), line: index + 1, rule: rule.name })
        break // 每行最多记一条规则命中
      }
    }
  })
  return findings
}

/** 打印分级报告 */
function printReport(files, findings) {
  const byLevel = {
    HIGH: findings.filter(f => f.level === 'HIGH'),
    MEDIUM: findings.filter(f => f.level === 'MEDIUM'),
    INFO: findings.filter(f => f.level === 'INFO'),
  }

  const fmt = f =>
    `${f.file}:${f.line} | [${f.rule}] ${f.type}${f.value ? ' | 值: ' + mask(f.value) : ''}`

  console.log('=== 安全扫描报告（静态敏感信息） ===')
  console.log(`扫描文件：${files.length} 个 | 规则：${RULES.map(r => r.name).join('、')}`)
  console.log('')

  if (byLevel.HIGH.length > 0) {
    console.log(`🔴 HIGH（真实密钥/私钥，立即处理）：${byLevel.HIGH.length} 处`)
    byLevel.HIGH.forEach(f => console.log('  ' + fmt(f)))
    console.log('')
  }
  if (byLevel.MEDIUM.length > 0) {
    console.log(`🟠 MEDIUM（需人工确认）：${byLevel.MEDIUM.length} 处`)
    byLevel.MEDIUM.forEach(f => console.log('  ' + fmt(f)))
    console.log('')
  }
  if (byLevel.INFO.length > 0) {
    console.log(`🟡 INFO（占位符/测试值，通常安全）：${byLevel.INFO.length} 处`)
    byLevel.INFO.forEach(f => console.log('  ' + fmt(f)))
    console.log('')
  }
  if (byLevel.HIGH.length + byLevel.MEDIUM.length + byLevel.INFO.length === 0) {
    console.log('✅ 未发现硬编码敏感信息')
    console.log('')
  }

  console.log('提示：SQL 注入、IPC 暴露、Electron 配置等语义风险请执行 /security-audit 技能人工审查。')
}

const files = resolveTargets(process.argv.slice(2))
const allowlist = loadAllowlist()
// 过滤人工确认豁免的命中(默认值/测试值/误报,见 security-allowlist.json)
const findings = files.flatMap(scanFile).filter(f => !allowlist.has(`${f.file}:${f.line}`))
printReport(files, findings)

// 退出码：1 = 存在 HIGH/MEDIUM 风险（供 CI/hook 检测；技能交互执行时输出正常即视为成功）
process.exit(findings.some(f => f.level !== 'INFO') ? 1 : 0)
