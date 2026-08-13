#!/usr/bin/env node
/**
 * git commit 质量门禁校验（pre-commit hook 的唯一入口）
 *
 * 校验两件事：
 * ① 门禁标记新鲜度：.claude/markers/test-passed.json 与 quality-passed.json
 *    必须存在、passed=true、headSha 与当前 HEAD 一致、timestamp 在 30 分钟时限内；
 * ② 二次实时扫描：security-scan.js + check-comments.js 退出码必须为 0
 *    （标记可能过期，扫描结果永远新鲜，作为兜底复核）。
 *
 * 全部通过 exit 0，任一失败打印中文原因并 exit 1。
 * 被 scripts/hooks/pre-commit 调用；也可手动 `node scripts/gate-check.js` 调试。
 */

import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

/** 两个门禁标记文件及其对应的 agent 名称（用于错误提示） */
const MARKERS = {
  'test-passed.json': 'tester（单元测试）',
  'quality-passed.json': 'quality-engineer（质量检查）',
}

/** 标记之外的实时兜底扫描：脚本已内置「exit 1 = 失败，供 CI/hook 检测」语义 */
const SCANS = [
  { script: 'scripts/security-scan.js', label: '安全扫描' },
  { script: 'scripts/check-comments.js', label: '注释检查' },
]

const MAX_AGE_MS = 30 * 60 * 1000 // 标记最长有效 30 分钟
const FUTURE_SKEW_MS = 5 * 60 * 1000 // 时间戳超前超过 5 分钟视为异常（防伪造/时钟问题）

// ---------- 基础信息 ----------

const root = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim()
// 兼容首次提交(仓库尚无 HEAD):rev-parse 失败时 headSha 用空字符串,
// 标记写入方在 git rev-parse HEAD 失败时也写空字符串,两者一致即通过。
let headSha = ''
try {
  headSha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
} catch {
  /* 首次提交前无 HEAD,headSha 保持空 */
}

const errors = []

// ---------- ① 标记文件校验 ----------

/**
 * 校验单个标记文件，失败原因写入 errors。
 * 区分五种失败形态，各自给出可操作的修复提示。
 */
function checkMarker(fileName, agentName) {
  const filePath = path.join(root, '.claude', 'markers', fileName)

  if (!existsSync(filePath)) {
    errors.push(`【门禁】缺少 ${fileName}：未运行过 ${agentName}，或运行未完成`)
    return
  }

  let marker
  try {
    marker = JSON.parse(readFileSync(filePath, 'utf8'))
  } catch {
    errors.push(`【门禁】${fileName} 损坏（无法解析 JSON），请重新运行 ${agentName}`)
    return
  }

  if (marker.passed !== true) {
    errors.push(`【门禁】${fileName} 判定为未通过：${marker.reason || 'passed 不为 true'}`)
    return
  }
  if (typeof marker.headSha !== 'string' || marker.headSha !== headSha) {
    errors.push(
      `【门禁】${fileName} 对应的 HEAD 已过期（标记=${String(marker.headSha).slice(0, 7)}，当前=${headSha.slice(0, 7)})：` +
        '检查之后代码有改动，请重新运行 gitcommit-agent'
    )
    return
  }

  const ts = Date.parse(marker.timestamp)
  if (!Number.isFinite(ts)) {
    errors.push(`【门禁】${fileName} 的时间戳无效（${marker.timestamp}），请重新运行 ${agentName}`)
    return
  }
  if (ts > Date.now() + FUTURE_SKEW_MS) {
    errors.push(`【门禁】${fileName} 的时间戳异常超前（${marker.timestamp}），请重新运行 ${agentName}`)
    return
  }
  if (Date.now() - ts > MAX_AGE_MS) {
    errors.push(`【门禁】${fileName} 已超过 30 分钟时限（${marker.timestamp}），请重新运行 gitcommit-agent`)
  }
}

for (const [fileName, agentName] of Object.entries(MARKERS)) {
  checkMarker(fileName, agentName)
}

// ---------- ② 二次实时扫描 ----------

for (const { script, label } of SCANS) {
  // stdio: 'inherit' 让扫描报告直接输出到终端，用户能看到具体问题
  const result = spawnSync(process.execPath, [script], { cwd: root, stdio: 'inherit' })
  if (result.status !== 0) {
    errors.push(`【门禁】${label}未通过（exit ${result.status}），问题见上方输出`)
  }
}

// ---------- 汇总 ----------

if (errors.length > 0) {
  console.log('\n========== Git 提交门禁：未通过 ==========')
  for (const err of errors) console.log(err)
  console.log('请先运行 gitcommit-agent（或修复上述问题后重新运行），再提交。')
  process.exit(1)
}

console.log('✅ 门禁通过：单元测试与质量检查标记有效，二次扫描无问题。')
