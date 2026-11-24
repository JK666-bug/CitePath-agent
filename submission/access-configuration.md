# Access, Configuration, and Runtime Prompts

## Credentials

From the repository root, run `python3.11 tools/configure_local.py` to create `.env` for Docker Compose and `backend/.env` for FastAPI. The script generates random local credentials for MySQL and MinIO. Select a model provider and enter its API key in `backend/.env`. Build the submission from the blank template and source files, excluding the generated `.env` files, `volumes/`, `backend/data/pdfs/`, virtual environments, and `node_modules/`. Values already set in the process environment take precedence over the backend configuration file. [Blank configuration template](../backend/.env.example) · [Configuration script](../tools/configure_local.py)

The evaluation uses public teaching material and synthetic fixtures. At runtime, the selected cloud model may receive relevant PDF excerpts, questions, or answers. Course Q&A may contact external search services when Web search is enabled.

## Existing installations

For an existing MySQL and Milvus installation, use that installation's connection details in `backend/.env`. MySQL credentials set in Compose apply when its data volume is first initialized. To verify the submission while preserving existing courses and services, extract a second source copy and use a separate Compose project and ports.

After generating configuration in the second copy, add the following settings to its root `.env`.

```dotenv
COMPOSE_PROJECT_NAME=citepath-submission-test
CITEPATH_MYSQL_PORT=13306
CITEPATH_MILVUS_PORT=29530
CITEPATH_MILVUS_HEALTH_PORT=19091
```

In the second copy's `backend/.env`, set `MYSQL_PORT=13306` and `MILVUS_URI=http://127.0.0.1:29530`. Start the backend with `--port 18000`. Before starting the frontend, set `CITEPATH_API_TARGET` in the terminal environment to `http://127.0.0.1:18000` and launch Vite with `--port 15173`. Run the verification script with `--base-url http://127.0.0.1:18000`. Adjust these ports if they are already in use. [Main README](../README.md#2-setup-and-launch)

## Windows PowerShell

From the repository root, generate the local configuration.

```powershell
py -3.11 tools/configure_local.py
```

Set the model provider and API key in `backend/.env` as described in the main README. Then start the data services, import the schema, and launch the backend.

```powershell
docker compose up -d --wait mysql milvus
Get-Content .\backend\db\schema.sql -Raw | docker compose exec -T mysql sh -c 'MYSQL_PWD=$MYSQL_PASSWORD exec mysql -u citepath_agent citepath_agent'
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Use a second terminal to start the frontend with the commands in the main README. For evaluation commands, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`. To include the MySQL tests, set `$env:CITEPATH_SYNC_MYSQL_TESTS = '1'` in the backend test terminal before running `unittest`.

## Test doubles and operating limits

- The planner comparison uses `ObservingModel` as a test double for model tool selection. The `--live` comparison and API acceptance suite use the configured model provider. `Fixed rules` is the application's rule-based scheduling baseline.
- The PDF pipeline disables OCR, structured table extraction, and formula recognition. Scanned PDFs and pages that rely on diagrams may yield limited evidence. Retrieval can continue without the optional reranker. The PDF Q&A acceptance checks disable Web search.
- Full upload, generation, and scheduling workflows depend on MySQL, Milvus, available model weights, network access, and valid model credentials. Provider quota and response timeouts can affect those workflows. [Evaluation results](../evaluation/README.md#recorded-acceptance-results)

## Runtime prompts

The following source files contain the application's model instructions, tool definitions, and configuration.

| Function | Source files |
| --- | --- |
| AI scheduling, state inspection, tool selection, validation, and stopping | [planner.py](../backend/agent/planner.py) |
| PDF chapter and concept extraction | [chapterization.py](../backend/agent/chapterization.py) · [plan.py](../backend/agent/plan.py) |
| Adaptive practice, concept selection, and question format | [Practice instructions](../backend/agent/skills/practice/SKILL.md) · [practice_decision.py](../backend/agent/practice_decision.py) |
| Practice and exam generation and grading | [practice.py](../backend/agent/practice.py) · [exam.py](../backend/agent/exam.py) · [score.py](../backend/grading/score.py) |
| Course Q&A, course status, and PDF reader Q&A | [Q&A instructions](../backend/agent/skills/qa/SKILL.md) · [Course instructions](../backend/agent/skills/course/SKILL.md) · [qa.py](../backend/agent/qa.py) |
| Notes | [notes.py](../backend/agent/notes.py) |
| Models, dependencies, and services | [llm.py](../backend/agent/llm.py) · [Environment template](../backend/.env.example) · [Docker Compose](../docker-compose.yml) |

The [AI use declaration](ai-use-declaration.md) records the use of AI during project development.
