---
name: git-save
description: git 提交技能。分析工作区改动，按本项目中文提交信息风格生成信息并执行 git add + git commit（提交前会触发 pre-commit 门禁 hook）。当 gitcommit-agent 调用、或用户说「提交代码」「保存代码」「commit」时使用。
---

# git 提交技能（git-save）

## 步骤

1. **盘点**：`git status --porcelain`、`git diff --stat`、`git diff`（已 staged 与未 staged 均看），理解改动意图与范围。
2. **参考风格**：`git log --oneline -10`，沿用既有风格（单行中文、无 body 或极简 body）。
3. **生成提交信息**：格式「功能域+动作：要点（、要点…）」，示例：
   - 「知识库入库：5 种格式解析 + 中文切分 + Qdrant 批量写入」
   - 「问答管线：多轮改写 + 云端重排 + 引用溯源」
   - 「修复：SSE 帧 CRLF 解析 + 检索多样性采样」
   - 常用功能域：认证、会话、问答、知识库、检索、前端、后端、修复、重构、测试、脚本、构建、文档。
4. **暂存**：`git add <改动文件清单>`（从 git status 取，含新增文件）；确认清单完整后再执行。
5. **提交**：`git commit -m "<提交信息>"`。此时 pre-commit hook 会做最终门禁校验（标记新鲜度 + 安全/注释扫描）——这是权威闸门：提交被拒绝就把 hook 的中文输出原样汇报，绝不擅自 `--no-verify`（用户明确要求除外）。
6. **确认**：`git log -1 --format=%h %s`，汇报 commit hash 与提交信息。

## 规则

- 禁止 `--no-verify`（除非用户明确要求）；禁止跳过门禁。
- 提交信息必须中文、简洁、准确反映改动内容；不提交与改动无关的文件。
- `.env`、`node_modules/`、`.venv/`、`backend/data/`、`dist/` 等已被 .gitignore 排除，绝不可手动 `git add -f` 强制加入。
