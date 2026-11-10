# CitePath

An agent that helps a student study from course PDFs.

Need Docker Desktop, Python 3.10, and Node.js. Commands are for PowerShell.

## First time

From the repository root:

```powershell
docker compose up -d
Get-Content .\backend\db\schema.sql -Raw | docker exec -i citepath-agent-mysql mysql -ucitepath_agent -pcitepath_agent citepath_agent
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

Put your key in `backend/.env` as `HKU_API_KEY`. Then start the API and leave the window open:

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
preserving completed tasks and chapter identity; adding PDFs does not rebuild those
chapter boundaries. Study-time estimation remains pending.

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
