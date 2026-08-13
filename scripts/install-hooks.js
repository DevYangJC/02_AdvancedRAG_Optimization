#!/usr/bin/env node
/**
 * 安装 git pre-commit 门禁 hook（幂等）
 *
 * 把 scripts/hooks/pre-commit 模板复制到 git hooks 目录（.git/hooks/pre-commit）。
 * 幂等规则：目标不存在 → 写入；内容相同 → 跳过；内容被改过 → 从模板重置。
 *
 * Windows 关键细节：写入前统一换行为 \n，否则 CRLF 会破坏 shebang 导致 hook 无法执行。
 */

import { execFileSync } from 'node:child_process'
import { chmodSync, existsSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 仓库根：本文件位于 <root>/scripts/install-hooks.js，向上两级
const repoRoot = realpathSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..'))

const templatePath = path.join(repoRoot, 'scripts', 'hooks', 'pre-commit')
const hooksDir = path.resolve(execFileSync('git', ['rev-parse', '--git-path', 'hooks'], { encoding: 'utf8' }).trim())
const targetPath = path.join(hooksDir, 'pre-commit')

// 模板内容统一为 LF 换行：CRLF 会破坏 shebang
const template = readFileSync(templatePath, 'utf8').replace(/\r\n/g, '\n')
const normalize = (text) => text.replace(/\r\n/g, '\n')

/** 写入目标并设置可执行权限（Windows 上 chmod 为无操作） */
function writeHook() {
  writeFileSync(targetPath, template, 'utf8')
  try {
    chmodSync(targetPath, 0o755) // macOS/Linux 保证可执行
  } catch {
    /* 权限设置失败不影响提交门禁功能 */
  }
}

// ---------- 幂等安装 ----------

if (!existsSync(targetPath)) {
  writeHook()
  console.log(`✅ 已安装 pre-commit hook → ${targetPath}`)
} else if (normalize(readFileSync(targetPath, 'utf8')) === template) {
  console.log('pre-commit hook 已是最新，跳过。')
} else {
  writeHook()
  console.log('✅ 检测到安装后的 hook 被修改，已从模板重置。')
}

// ---------- 安全检查（仅警告，不阻断） ----------

const gitignorePath = path.join(repoRoot, '.gitignore')
if (!existsSync(gitignorePath) || !readFileSync(gitignorePath, 'utf8').includes('.claude/markers/')) {
  console.warn('⚠️ 警告：.gitignore 未忽略 .claude/markers/，标记文件可能被误提交')
}

const trackedMarkers = execFileSync('git', ['ls-files', '.claude/markers/'], { encoding: 'utf8' }).trim()
if (trackedMarkers) {
  console.warn('⚠️ 警告：以下标记文件已被 git 跟踪（应取消跟踪并忽略）：\n' + trackedMarkers)
}

// ---------- 结束提示 ----------

console.log('\n门禁已生效：下次 git commit 将自动校验单元测试与质量检查标记。')
console.log('提示：正式提交前先运行一次 gitcommit-agent 生成有效标记。')
