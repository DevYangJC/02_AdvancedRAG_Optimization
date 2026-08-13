---
name: unit-test
description: 为 LangChainRAG 知识库问答系统（FastAPI 后端 + Vue3 前端）编写、执行单元测试并输出测试报告。当用户说「写测试」「跑测试」「单元测试」「测试报告」「测一下 xx 模块」或输入 /unit-test 时使用。用法：/unit-test [目标路径|--all] [--html]
---

# 单元测试技能（unit-test）

## 技术栈（方案已确认，勿更换）

| 组件 | 说明 |
|---|---|
| pytest + pytest-asyncio | 后端测试运行器（配置在 backend/pytest.ini，asyncio_mode=auto） |
| httpx ASGITransport | 后端 API 集成测试（不触发 lifespan,conftest 手动初始化 DB） |
| Vitest 4 | 前端测试运行器，配置在 frontend/vite.config.ts 的 `test` 字段 |
| @vue/test-utils + jsdom | 前端 Vue 组件测试 |
| @vitest/coverage-v8 | 前端覆盖率统计，`--coverage` 时生成 HTML 报告于 frontend/coverage/index.html |

## 常用命令

```bash
# 后端（在 backend/ 目录）
.venv/Scripts/python.exe -m pytest            # 全部后端测试
.venv/Scripts/python.exe -m pytest tests/test_auth.py -v   # 定向

# 前端（在 frontend/ 目录）
npm run test            # 单次执行全部测试（vitest run）
npm run test:watch      # 监听模式
npm run test:coverage   # 执行 + 覆盖率（HTML 报告 frontend/coverage/index.html）
npx vitest run <路径>   # 只跑指定测试文件
```

## 参数说明

| 参数 | 行为 |
|---|---|
| （无参数）或 `--all` | 全量：若已有测试则执行全部；若尚无测试则为全部可测模块生成 |
| `<相对路径>` | 仅针对该文件/目录生成并运行测试 |
| `--html` | 附加覆盖率运行，生成 HTML 报告，报告末尾附其相对路径 |

## 执行流程

1. **分析目标代码**：读取目标文件，识别可测单元（纯逻辑函数、服务层、API 路由、composable、store、组件）与依赖（数据库、Qdrant、阿里云 API、localStorage、fetch）。
2. **确定测试策略**：按下方「测试策略表」逐模块选择 mock 方案。
3. **编写测试文件**：严格遵循「测试约定」。
4. **执行测试**：后端 `.venv/Scripts/python.exe -m pytest`；前端 `npm run test`。
5. **失败处理**：先判断失败原因——
   - **测试代码缺陷**（mock 配置错、断言错、环境问题）：直接修复后重跑；
   - **被测代码缺陷**：报告用户并给出修复建议，**不擅自修改业务逻辑**（除非用户明确要求）。
6. **输出报告**：按「报告格式」输出；带 `--html` 时先跑 `npm run test:coverage` 再附报告路径。

## 测试约定（硬性规范）

### 后端（backend/tests/）

1. **位置与命名**：`backend/tests/test_<模块>.py`,与 app/ 目录结构对应。
2. **环境变量必须在导入 app 前设置**（conftest.py 已处理）：测试库 `data/test.db`、独立上传目录、测试 JWT secret、清空 API Key。**新增测试文件不得在 conftest 之前 import app 模块**。
3. **API 测试**：用 `client` fixture（httpx AsyncClient + ASGITransport）；认证用 `admin_token` / `user_tokens` fixture；`auth_headers(token)` 生成请求头。
4. **用户名唯一性**：注册类测试用 `unique_name(prefix)` 生成唯一用户名（测试库持久化,固定用户名第二次运行会 400）。
5. **外部依赖**：pytest 不依赖 Qdrant / 阿里云 API / 后端服务运行（conftest 已禁用限流）。涉及外部服务的路径用 mock 或只测错误分支。
6. **纯函数测试**：切分器、编码探测、语义缓存 normalize/hash 等直接调用断言。
7. **测试间隔离**：每个用例独立事务/数据,不共享状态;清理类测试注意外键顺序（先删 messages 再删 conversations）。

### 前端（frontend/src/__tests__/）

1. **位置与命名**：`src/__tests__/<被测文件名>.spec.ts`,与 src/ 结构对应;测试辅助放 `src/test/`。
2. **显式 import vitest API**（`import { describe, it, expect, vi, beforeEach } from 'vitest'`）——**不开 globals**。测试文件参与 `vue-tsc -b` 构建类型检查,类型必须干净。
3. **环境**：默认 jsdom（vite.config.ts test 字段配置）。
4. **mock localStorage / fetch / axios**：
   - store 测试：mock `@/api/*` 模块（`vi.mock('@/api/chat', ...)`）,不触真实网络；
   - useSSE 测试：mock 全局 `fetch` 返回 ReadableStream 模拟 SSE 帧；
   - 组件测试：`mount` + `global.plugins: [ElementPlus]` 或 stubs 隔离。
5. **失败用例打印 console.error 时**：`vi.spyOn(console, 'error').mockImplementation(() => {})` 抑制噪音,测试结束 `mockRestore()`。

## 测试策略表

| 被测对象（后端） | 策略 |
|---|---|
| 纯逻辑 / 工具（splitters、loaders、cache_service、security） | 直接调用,断言输入→输出 |
| API 路由（auth / conversations / documents） | `client` fixture 发起真实 HTTP 请求;认证/权限/越权用例用 fixture token |
| 服务层（auth_service、document_service 校验逻辑） | 直接调 + 内存 SQLite 会话;涉及向量库的路径 mock 或跳过 |
| 语义缓存 | 真实 SQLite 表读写,断言 normalize/hash/TTL 失效/清理 |

| 被测对象（前端） | 策略 |
|---|---|
| 纯函数（useMarkdown 渲染、引用编号替换） | 直接调用,断言 HTML 输出 |
| composable（useSSE 拆帧/事件分发） | mock fetch 返回流式响应,断言回调序列 |
| Pinia store（auth / chat） | `createPinia()` + `setActivePinia()`;mock `@/api/*` 模块 |
| api client（401 刷新/单飞/错误提示） | mock localStorage + 拦截器行为断言 |

## 覆盖率目标

- 新增测试需覆盖被测模块主要分支：语句 ≥ 70%、分支 ≥ 60% 起步
- 覆盖率不足时在报告中说明差距与补测建议,不强行凑数
- 报告必须给出 语句/分支/函数/行 四项覆盖率

## 报告格式

```text
### 测试报告（YYYY-MM-DD HH:mm）
- 测试文件 N 个 / 用例 M 个
- 通过 X / 失败 Y / 跳过 Z
- 执行耗时 T s
- 覆盖率（前端,可选）：语句 a% / 分支 b% / 函数 c% / 行 d%
- 失败详情：文件:行号 + 原因 + 修复建议（有失败时）
- 薄弱模块 / 遗漏场景：…
```

带 `--html` 时,追加：`HTML 报告：frontend/coverage/index.html`（相对项目根目录）。

## 规则

- 涉及新技术方案（新框架、新库、策略调整）必须列出方案等待用户选择,严禁擅自实施。
- 被测代码确有缺陷时只报告、不擅自修改业务逻辑;用户明确要求修复时方可修复。
- 写新测试前先检查 `backend/tests/` 与 `frontend/src/__tests__/` 是否已有同类测试,避免重复。
