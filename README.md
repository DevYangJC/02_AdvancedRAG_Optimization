<div align="center">

# 🚀 Enterprise RAG Optimization Platform
### 基于 LangChain + FastAPI + Vue 3 的企业级 RAG 检索增强生成优化平台

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Vue3](https://img.shields.io/badge/Vue.js-3.5-4FC08D.svg?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Qdrant](https://img.shields.io/badge/Qdrant-VectorDB-red.svg?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[English](./README_EN.md) | **中文文档**

<p align="center">
  <b>专注于高并发、低延迟、精确溯源与双重缓存的企业级电商/通用商品知识库问答系统</b>
</p>

</div>

---

## 🌟 核心特性与技术亮点

### 🧠 1. 混合检索与双重精排 (Hybrid RAG & Reranking)
* **密集向量检索 (Dense Retrieval)**：基于 Qdrant 向量数据库，使用 1024 维 `text-embedding-v3` / `qwen3.7-text-embedding` 进行毫秒级粗召回（Top-100）。
* **二次重排序 (Rerank 精排)**：整合 DashScope 原生 `gte-rerank-v2` / 硅基流动重排模型，对候选知识块做深度交叉打分，精确挑选 Top-6 上下文。
* **多轮意图改写 (Contextual Query Rewrite)**：利用 LCEL 编排多轮对话语义改写，自动补全追问主语（如："那电池呢" ➔ "星云手机 X1 电池容量？"）。

### ⚡ 2. 双重缓存引擎 (Double-Caching Engine)
* **语义问答缓存 (Semantic Response Cache)**：利用标准化问题 MD5 哈希与数据库结合，高频 FAQ 提问毫秒级直接命中回答，极大节省付费 LLM API 额度。
* **磁盘向量缓存 (CacheBackedEmbeddings)**：引入 LangChain `LocalFileStore` 磁盘缓存层，重复解析或服务重启无需重新向量化，实现零成本复用。

### 🛡️ 3. 高并发与企业级工程架构
* **全异步技术栈 (Full-Async Architecture)**：FastAPI + SQLAlchemy Async Engine + `asyncpg` / `aiosqlite` 高性能数据库连接池。
* **限流与熔断重试 (Rate Limit & Resilience)**：基于 `slowapi` 实施 IP 级别限流防刷，结合 `tenacity` 指数退避重试与信号量并发控制（Semaphore=8）。
* **全链路追踪 (Request-ID Tracing)**：注入 HTTP Request-ID 中间件，实现从请求接入、检索打分到 SSE 流式响应的全链路日志跟踪。

### 🎨 4. 现代暗黑极简 UI/UX
* **全新一站式主导航侧边栏**：无缝融合“知识问答”与“文档管理”两大功能模块，支持一键收起折叠。
* **实时 SSE 逐字流式打字**：首 Token 秒级响应，提供交互式引用来源便签、相关度打分与问答点赞/点踩反馈。
* **多格式知识库解析**：支持 PDF、DOCX、XLSX、TXT、MD 五种常用格式，解析进度实时可视化，提供递归切片预览。

---

## 🏗️ 系统架构图

```
                       ┌──────────────────────────────────────────┐
                       │  Web 浏览器端 (Vue 3 + TS + Element Plus) │
                       └────────────────────┬─────────────────────┘
                                            │
                                            ├──────► REST API (Axios + JWT)
                                            └──────► SSE 流式问答 (Fetch API)
                                                    │
┌───────────────────────────────────────────────────▼───────────────────────────────────────────────────┐
│                                FastAPI 后端服务 (:8000 Async)                                          │
│                                                                                                       │
│  ┌────────────────────────┐   ┌──────────────────────────┐   ┌─────────────────────────────────────┐  │
│  │   Auth / Security      │   │  Ingestion Task Queue    │   │  RAG Chain Pipeline (LCEL)          │  │
│  │ JWT Dual Token / bcrypt│   │ Async Chunking & Embed   │   │ Rewrite ➔ Retrieve ➔ Rerank ➔ LLM   │  │
│  └────────────────────────┘   └──────────────────────────┘   └─────────────────────────────────────┘  │
└───────────────────────┬───────────────────────────┬───────────────────────────────────┬───────────────┘
                        │                           │                                   │
      ┌─────────────────▼─────────────────┐   ┌─────▼───────────────────────┐   ┌───────▼────────────────────────┐
      │  关系型数据库                     │   │  向量数据库                  │   │  云端大模型 API                │
      │  SQLite / PostgreSQL (asyncpg)    │   │  Qdrant (1024 维 Cosine)    │   │  阿里云百炼 / 硅基流动          │
      │  User/Doc/Chunk/Conv/Message/Cache│   │  Dense Vector & Payload     │   │  Qwen-Plus/Max · Embedding/Rerank│
      └───────────────────────────────────┘   └─────────────────────────────┘   └────────────────────────────────┘
```

---

## 🛠️ 技术栈对比

| 模块 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **Web 前端** | Vue 3 + TypeScript + Vite + Element Plus + Pinia | 响应式双栏工作台、SSE 拆帧解构、Markdown 极速渲染 |
| **应用后端** | Python 3.10+ / FastAPI / Pydantic v2 / slowapi | 全异步非阻塞架构，RESTful + SSE 实时流输出 |
| **RAG 框架** | LangChain / LCEL / CacheBackedEmbeddings | 灵活表达 RAG 问答链，内嵌磁盘缓存与批量调度 |
| **向量数据库** | Qdrant Vector Search Engine (:6333) | 1024 维高维向量搜索、Payload 条件过滤与级联清理 |
| **关系型数据库** | PostgreSQL (asyncpg) / SQLite (aiosqlite) | 事务级异步 ORM，支撑用户、文档元数据、历史会话与缓存 |
| **云端 API** | 通义百炼 DashScope / 硅基流动 SiliconFlow | `qwen-plus`/`qwen-max` 对话，`text-embedding-v3`，`gte-rerank-v2` |

---

## ⚡ 快速开始

### 1. 前置环境准备

* **Python** 3.10+
* **Node.js** 18+ (推荐 v20+)
* **Qdrant 向量库** (可通过 Docker 或本地二进制文件运行)
* **PostgreSQL (可选)** 或使用默认嵌入式 **SQLite**

### 2. 部署基础组件 (Docker)

如果你已有 Docker 环境，推荐快速启动 PostgreSQL (pgvector) 与 Qdrant 容器：

```bash
# 启动 Qdrant 向量库
docker run -d --name rag-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant

# (可选) 启动 PostgreSQL 数据库
docker run -d --name rag-postgres -e POSTGRES_USER=root -e POSTGRES_PASSWORD=123456 -e POSTGRES_DB=argus_rag -p 5433:5432 pgvector/pgvector:pg16
```

### 3. 后端服务配置与启动

```bash
# 进入后端目录
cd backend

# 创建并激活 Python 虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 配置环境变量
copy .env.example .env
```

编辑 `backend/.env` 文件，填入你的大模型密钥与数据库配置：

```env
DASHSCOPE_API_KEY=sk-xxxxxx
DATABASE_URL=postgresql+asyncpg://root:123456@localhost:5433/argus_rag
QDRANT_URL=http://localhost:6333
```

生成测试样本数据并启动 FastAPI 服务：

```bash
# 生成 5 种格式事实锚点测试样本
python -m scripts.create_test_data

# 启动后端 (支持热重载)
uvicorn app.main:app --reload --port 8000
```

> 网页访问接口文档：http://localhost:8000/api/docs  
> 健康检查端口：http://localhost:8000/api/health

### 4. 前端应用启动

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

在浏览器中打开 **`http://localhost:5173`** 即可进入系统。

* 默认管理员账号：`admin`
* 默认管理员密码：`123456`

---

## 🧪 测试与性能压测

项目提供了完整的自动化单元测试、端到端冒烟测试及高并发性能压测脚本：

```bash
cd backend

# 1. 运行单元测试套件
pytest -v

# 2. 运行端到端全链路冒烟测试 (需后端、Qdrant 与 API Key 准备就绪)
python -m scripts.e2e_smoke

# 3. 运行高并发性能压测
python -m scripts.perf_test --concurrency 5 --questions 10
```

---

## 📁 目录结构导览

```text
02_AdvancedRAG_Optimization/
├── backend/                  # Python FastAPI 后端源码
│   ├── app/
│   │   ├── api/v1/          # RESTful 与 SSE 路由控制器
│   │   ├── core/            # 核心配置、安全鉴权、日志与异常处理
│   │   ├── db/              # SQLAlchemy 异步引擎与 Session
│   │   ├── models/          # 数据库模型 (User, Document, Chunk, Message 等)
│   │   ├── rag/             # LangChain RAG 核心管线 (Loader, Splitter, Embedder, Reranker, Chain)
│   │   ├── services/        # 业务逻辑服务层 (Vector, Document, Chat, Cache)
│   │   └── tasks/           # Asyncio 异步文档解析入库任务
│   ├── scripts/             # 预置脚本 (数据生成、冒烟测试、性能压测)
│   └── tests/               # Pytest 自动化测试套件
├── frontend/                 # Vue 3 前端源码
│   ├── src/
│   │   ├── api/             # Axios 接口封装与拦截器
│   │   ├── components/      # UI 核心组件 (Chat, Sidebar, MessageItem)
│   │   ├── composables/     # Vue 组合式函数 (useSSE, useMarkdown)
│   │   ├── stores/          # Pinia 状态管理 (Auth, Chat)
│   │   └── views/           # 页面视图 (MainLayout, ChatView, AdminKnowledgeView)
└── docs/                     # 架构文档与测试数据
```

---

## ❓ 常见问题解答 (FAQ)

<details>
<summary><b>1. 如何切换至硅基流动 (SiliconFlow) 的向量模型与重排序模型？</b></summary>
<br>
答：只需要在 <code>backend/.env</code> 中将 <code>DASHSCOPE_BASE_URL</code> 改为 <code>https://api.siliconflow.cn/v1</code>，并将 <code>EMBEDDING_MODEL</code> 设为 <code>BAAI/bge-m3</code> 即可。针对 Reranker，硅基流动的 API 响应格式稍有不同，项目自带兼容解析逻辑。
</details>

<details>
<summary><b>2. 如果我想从 SQLite 切换到 PostgreSQL，需要手动建表吗？</b></summary>
<br>
答：不需要！后端启动时会在 FastAPI <code>lifespan</code> 周期中自动调用 <code>Base.metadata.create_all</code>，在 PostgreSQL 中自动建立所需的所有数据表及索引，并自动注入默认管理员账号。
</details>

<details>
<summary><b>3. 为什么知识库切片解析是异步任务？如何感知进度？</b></summary>
<br>
答：由于长文档 Parsing、Text Splitting 和 Embedding 需要多次云端 API 交互，后端使用后台 Task 队列处理。前端在“文档管理”页面内置了 3 秒自动轮询逻辑，可实时渲染解析进度条。
</details>

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 许可证开源。自由使用、修改与商业分发。
