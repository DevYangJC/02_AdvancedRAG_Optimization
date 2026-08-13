/**
 * 注释密度检查脚本（comments-check 技能配套）
 *
 * 统计项目中代码文件的注释行数与代码行数，计算注释密度。
 * 目标密度：注释行 ≈ 代码行的 30%（10 行中 3 行注释 7 行正文）。
 *
 * 用法：
 *   node scripts/check-comments.js                # 扫描全项目
 *   node scripts/check-comments.js src/stores     # 扫描指定目录/文件
 *   node scripts/check-comments.js src/views/Record.vue src/stores/ledger.ts
 *
 * 统计口径：
 *   - 注释行：独立成行的注释（//、/* *​* /、.vue 模板中 <!-- -->），行内注释不计入
 *   - 代码行：非空且非注释的行
 *   - 密度 = 注释行 / (注释行 + 代码行)
 *   - 达标区间 25%~35%；<25% 注释不足；>40% 注释冗余
 */
import fs from 'node:fs'
import path from 'node:path'

/** 排除的目录 */
const EXCLUDE_DIRS = new Set([
  'node_modules', 'dist', 'dist-electron', 'coverage', 'release', '.git', '.claude', '.vite',
  '.venv', 'data', // LangChainRAG:Python 虚拟环境与运行时数据
])
/** 参与统计的文件扩展名 */
const SUPPORTED_EXT = new Set(['.ts', '.tsx', '.js', '.jsx', '.vue', '.py'])
/** 达标区间与冗余阈值 */
const TARGET_MIN = 0.25
const TARGET_MAX = 0.35
const OVER_MAX = 0.4

/**
 * 逐行状态机统计单个文件的注释行数 / 代码行数。
 * 处理 /* *​* / 块注释（跨行）与 .vue 模板 <!-- --> 注释（跨行）。
 */
function countLines(source) {
  let commentLines = 0
  let codeLines = 0
  let inBlock = false // /* */
  let inHtmlComment = false // <!-- -->

  for (const raw of source.split('\n')) {
    const line = raw.trim()
    if (line === '') continue

    if (inBlock) {
      commentLines++
      if (line.includes('*/')) inBlock = false
      continue
    }
    if (inHtmlComment) {
      commentLines++
      if (line.includes('-->')) inHtmlComment = false
      continue
    }
    if (line.startsWith('/*')) {
      commentLines++
      if (!line.includes('*/')) inBlock = true
      continue
    }
    if (line.startsWith('<!--')) {
      commentLines++
      if (!line.includes('-->')) inHtmlComment = true
      continue
    }
    if (line.startsWith('//')) {
      commentLines++
      continue
    }
    // Python 注释(LangChainRAG 后端)
    if (line.startsWith('#') && !line.startsWith('#!')) {
      commentLines++
      continue
    }
    codeLines++
  }
  return { commentLines, codeLines }
}

/** 递归收集受支持文件（相对路径） */
function collectFiles(dir, results = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (EXCLUDE_DIRS.has(entry.name)) continue
      collectFiles(path.join(dir, entry.name), results)
    } else if (SUPPORTED_EXT.has(path.extname(entry.name))) {
      results.push(path.join(dir, entry.name))
    }
  }
  return results
}

/** 按参数解析扫描目标：无参数扫全项目，有参数按文件/目录解析 */
function resolveTargets(args) {
  if (args.length === 0) return collectFiles(process.cwd())

  const files = []
  for (const arg of args) {
    const abs = path.resolve(arg)
    const stat = fs.statSync(abs)
    if (stat.isDirectory()) collectFiles(abs, files)
    else if (SUPPORTED_EXT.has(path.extname(abs))) files.push(abs)
  }
  return files
}

/** 生成密度统计报告（按达标/不足/冗余分组） */
function buildReport(files) {
  const records = files
    .map(file => {
      const source = fs.readFileSync(file, 'utf-8')
      const { commentLines, codeLines } = countLines(source)
      const total = commentLines + codeLines
      const density = total === 0 ? 0 : commentLines / total
      return { file: path.relative(process.cwd(), file), commentLines, codeLines, density }
    })
    .filter(r => r.commentLines + r.codeLines > 0) // 跳过空文件(__init__.py 等)不参与密度判定

  const insufficient = records.filter(r => r.density < TARGET_MIN)
  const ok = records.filter(r => r.density >= TARGET_MIN && r.density <= TARGET_MAX)
  const redundant = records.filter(r => r.density > OVER_MAX)

  const totalComments = records.reduce((s, r) => s + r.commentLines, 0)
  const totalCode = records.reduce((s, r) => s + r.codeLines, 0)
  const totalDensity = totalComments + totalCode === 0 ? 0 : totalComments / (totalComments + totalCode)

  return { records, insufficient, ok, redundant, totalComments, totalCode, totalDensity }
}

/** 打印报告 */
function printReport({ records, insufficient, ok, redundant, totalComments, totalCode, totalDensity }) {
  const fmt = r =>
    `${r.file}  注释 ${r.commentLines} 行 / 代码 ${r.codeLines} 行 = ${(r.density * 100).toFixed(1)}%`

  console.log('=== 注释密度检查报告 ===')
  console.log(`扫描文件：${records.length} 个 | 总注释行：${totalComments} | 总代码行：${totalCode}`)
  console.log(`总密度：${(totalDensity * 100).toFixed(1)}% （达标区间 25%~35%）`)
  console.log('')

  if (insufficient.length > 0) {
    console.log(`❌ 注释不足（<${TARGET_MIN * 100}%）：`)
    insufficient.sort((a, b) => a.density - b.density).forEach(r => console.log(`  ${fmt(r)}`))
    console.log('')
  }
  if (ok.length > 0) {
    console.log(`✅ 达标（${TARGET_MIN * 100}%~${TARGET_MAX * 100}%）：`)
    ok.forEach(r => console.log(`  ${fmt(r)}`))
    console.log('')
  }
  if (redundant.length > 0) {
    console.log(`⚠️ 注释过多（>${OVER_MAX * 100}%，检查冗余/无意义注释）：`)
    redundant.sort((a, b) => b.density - a.density).forEach(r => console.log(`  ${fmt(r)}`))
    console.log('')
  }
}

const files = resolveTargets(process.argv.slice(2))
const report = buildReport(files)
printReport(report)

// 退出码：1 = 存在注释不足的文件（供 CI/hook 检测；技能交互执行时输出正常即视为成功）
process.exit(report.insufficient.length > 0 ? 1 : 0)
