# CitePath 安装与使用（GitHub 版）

本文件面向第一次拿到源码的人。目标：在本机启动 CitePath，登录、建课、上传讲义、生成计划、做两轮练习、看报告、提问。

## 1. 需要什么

- Windows 10/11，PowerShell
- Docker Desktop（MySQL + Milvus + MinIO）
- Python 3.12
- Node.js 24（或 20+）与 npm
- 一个模型 API key：
  - DeepSeek：`DEEPSEEK_API_KEY`
  - 或 HKU：`HKU_API_KEY`

> 不要提交 `backend/.env`。仓库只带 `.env.example`。

## 2. 第一次启动

### 2.1 启动数据库与向量库

在仓库根目录：

```powershell
docker compose up -d
docker ps
```

应该看到：

- `citepath-agent-mysql`
- `citepath-agent-milvus`
- `citepath-agent-etcd`
- `citepath-agent-minio`

### 2.2 初始化表结构

```powershell
Get-Content .\backend\db\schema.sql -Raw |
  docker exec -i citepath-agent-mysql mysql -ucitepath_agent -pcitepath_agent citepath_agent
```

### 2.3 安装后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-windows.txt
copy .env.example .env
notepad .env
```

在 `.env` 里二选一：

**DeepSeek**

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your-deepseek-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

**HKU**

```env
LLM_PROVIDER=hku
HKU_API_KEY=<your-hku-key>
HKU_DEPLOYMENT=gpt-4.1-mini
HKU_API_VERSION=2025-04-01-preview
```

建议在 Windows 上把模型缓存放到短路径，避免路径过长：

```env
HF_HOME=C:/CitePathModels/hf
HF_HUB_CACHE=C:/CitePathModels/hf/hub
DOCLING_CACHE_DIR=C:/CitePathModels/docling
FASTEMBED_CACHE_PATH=C:/CitePathModels/fastembed
```

### 2.4 启动 API

保持这个窗口开着：

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

应返回：

```json
{"status":"ok"}
```

### 2.5 启动前端

另开一个 PowerShell：

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

打开：

**http://127.0.0.1:5173/**

## 3. 怎么用

### 3.1 注册和登录

- 打开 `http://127.0.0.1:5173/`
- 点注册，创建账号
- 登录后进入课程列表

### 3.2 创建课程并上传讲义

1. 新建课程，填课程名和简要说明。
2. 上传 PDF（建议先用 `data/mit-6.006-spring-2020/lecture-04.pdf` 试）。
3. 等待“已解析/已索引”。第一次运行会下载 Docling/fastembed 模型，可能几分钟。
4. 生成学习计划。计划会按章节拆分讲义。

> 上传的 PDF 要能选中文字；扫描图片 PDF 可能没有可用文本。

### 3.3 做两轮练习

1. 打开课程 → 选择章节 → 开始练习。
2. 先做第一轮（选择 + 简答）。
3. 提交后看分数：
   - 达到章节阈值（默认 80%）：结束；
   - 未达到：只针对薄弱概念生成第二轮；
   - 两轮后仍不通过：显示 `failed_after_2`，不会出第三轮。
4. 报告里会分开显示两轮分数、薄弱概念和错题解释。

### 3.4 课程问答

课程页的 Q&A：

- 问讲义里的概念；
- 回答会带来源页；
- 讲义没有依据时会说明不足，不强行编。

### 3.5 学习计划与日历

- 计划页可以改任务日期；
- 日历显示每天任务；
- 改计划会重排后续任务，不会丢掉已完成记录。

## 4. 下次启动

```powershell
docker compose up -d
```

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## 5. 常见问题

### 页面能开，但接口 502/连不上

- 确认 API 在 8000；
- `Invoke-RestMethod http://127.0.0.1:8000/api/health`；
- 前端 Vite 代理 `/api` 到 8000，改了端口要同步改 `frontend/vite.config.ts`。

### 上传 PDF 失败

- 确认 PDF 有可选中文字；
- 第一次解析会下载模型，检查 `backend/logs` 和 API 窗口；
- Windows 路径过长时，把 `HF_HOME` 等缓存改到短路径。

### 模型 401/403

- `.env` 的 key 与 `LLM_PROVIDER` 必须匹配；
- DeepSeek 的模型名用 `deepseek-chat`；
- 换 key 后重启 API。

### 端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue
```

换端口时同时改前端代理。

## 6. 安全

- 不提交 `backend/.env`；
- 不提交 `backend/storage/`、`volumes/`、`*.private.json`；
- 学生数据和上传 PDF 不要推到公开仓库；
- 共享截图前先打码账号和 key。

## 7. 评测工具（可选）

`tools/review-window/` 是人工标注窗口，`evaluation_assets/` 是评测数据。普通学习使用不需要它们。GitHub 源码包默认不包含评测数据，避免把标注/学生数据公开。
