# CitePath

An agent that helps a student study from course PDFs.

Need Docker Desktop, Python 3.12 (the tested runtime), and Node.js. Commands are for PowerShell.

## First time

From the repository root:

```powershell
docker compose up -d
Get-Content .\backend\db\schema.sql -Raw | docker exec -i citepath-agent-mysql mysql -ucitepath_agent -pcitepath_agent citepath_agent
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-windows.txt
copy .env.example .env
```

Select `LLM_PROVIDER=hku` or `LLM_PROVIDER=deepseek` in `backend/.env`, then fill
the selected provider's key and model settings from `.env.example`. Keep keys local.
On other operating systems, install `requirements.txt`; the Windows file pins the
`ujson` and `grpcio` wheels verified under this machine's application control policy.
Then start the API and leave the window open:

```powershell
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another window:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173/ and create an account.

## Next time

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

## Checks and current scope

From `backend`, using the configured virtual environment (the lightweight test
dependencies do not download PDF or embedding runtimes):

```powershell
.\.venv\Scripts\python -m pip install -r requirements-test.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
```

From `frontend`:

```powershell
npm ci
npm run build
npm run lint
```

The backend regression tests mock external services. They verify grading boundaries,
two-round practice, recovery, duplicate handling, ingestion and plan rescheduling;
they do not certify real model answer quality or a live MySQL/Milvus deployment.

Practice defaults to an 80% chapter threshold, fixed within each session, and stops
after passing or after round 2. A failed/incomplete short-answer model grade remains
retryable and cannot create an official score. Existing plans are rescheduled while
preserving completed tasks and chapter identity. See the status report for the
planning profile, workload estimate, incremental material update and version-history
features and their validation limits.

Original PDFs are stored in `backend/storage/uploads` by default. Set
`PDF_STORAGE_DIR` in the backend environment for another persistent directory, and
back up that directory along with MySQL and Milvus. Source links require the
owning user's login. Re-upload the same PDF to restore originals missing from
older records.

See [功能核对与续开发记录](docs/STATUS.zh-CN.md),
[前后端接口说明](frontend/BACKEND_INTEGRATION.zh-CN.md), and
[evaluation and configuration freezing](docs/EVALUATION.md) for implementation
status, remaining work and the distinction between regression tests and formal
evaluation targets.

The integration runner can collect actual development workflow observations after
the services and model are configured. See [live integration](docs/LIVE-INTEGRATION.md).
The latest upstream compatibility assessment is in [更新影响记录](docs/UPSTREAM-2026-11-12.zh-CN.md).
