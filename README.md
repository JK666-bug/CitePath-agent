# CitePath

- **Course** COMP7608B Large Language Models
- **Group** 41
- **Members** Jiang Kai, Shi Junying, Tao Yu, and Peng Luhan
- **Submission version** `CitePath-G41-20261124`

CitePath helps students turn course PDFs into chapter-based study plans. It supports reading, adaptive practice, chapter exams, and PDF Q&A with page citations. When availability or progress changes, students can preview a new schedule for their remaining work before publishing it to the calendar.

The submission contains the application source from `develop` at `7de948e9845ad9bc36598d84426d56db23ad83f3`, together with the submission configuration, sample inputs, and evaluation materials. Use the source snapshot included in the submission ZIP to reproduce this version.

## 1. Requirements

| Component | Requirements |
| --- | --- |
| Development environment | Python 3.11, Node.js 20.19+ in the 20.x series or 22.12+, npm, and Docker with Compose v2 or later. The recorded evaluation used macOS arm64, Python 3.11.18, Node.js 26.13.0, npm 11.20.0, and Docker Compose 5.6.0. |
| Backend | FastAPI 0.136.1, Uvicorn 0.46.0, LangChain 1.5.0, LangGraph 1.2.22, Docling 2.146.0, PyMuPDF 1.26.5, FastEmbed 0.7.4, and PyMilvus 2.6.2. See [backend requirements](backend/requirements.txt) for the full list. |
| Frontend | React 19.3.1, Vite 8.3.4, and TypeScript 6.0.3. Install the locked versions with `npm ci`. [Dependency lockfile](frontend/package-lock.json) |
| Local services | MySQL 8.4 stores accounts and study state. Milvus 3.0.3 stores the retrieval index and uses etcd 3.5.25 and MinIO. [Docker Compose configuration](docker-compose.yml) |
| Sample data and model downloads | Three sample PDFs are supplied. The first setup requires internet access to obtain images, packages, and model weights. PDF processing uses Docling layout analysis, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` embeddings, and optional `Xenova/ms-marco-MiniLM-L-6-v2` reranking. [Sample PDF sources](data/course-pdf-attribution.md) |
| Model access | Configure either the HKU student API or DeepSeek. The HKU defaults are deployment `gpt-4.1-mini` and API version `2025-04-01-preview`. HKU requires valid student API access and quota. DeepSeek defaults to `deepseek-flash` and requires an API key and available balance. Provider charges may apply. The application uses temperature 0. |
| Hardware | The application can run on a CPU. The evaluation machine allocated about 8 GiB of RAM to Docker. Allow several gigabytes of disk space for images, Python packages, and model caches. |

## 2. Setup and launch

The following commands use a macOS or Linux shell. See the [access and configuration guide](submission/access-configuration.md) for Windows PowerShell and for running alongside an existing installation.

From the repository root, generate the local environment files.

```bash
python3.11 tools/configure_local.py
```

Open `backend/.env`. For HKU, keep `LLM_PROVIDER=hku` and set `HKU_API_KEY`. For DeepSeek, set `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY`. The same file contains the deployment or model name. The setup script generates local MySQL and object storage credentials and stops if either environment file already exists.

Start the data services from the repository root. Import the schema for a fresh database.

```bash
docker compose up -d --wait mysql milvus
docker compose exec -T mysql sh -c 'export MYSQL_PWD="$MYSQL_PASSWORD"; exec mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"' < backend/db/schema.sql
```

Start the backend in the first terminal. The application entry point is `app` in `backend/main.py`.

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In a second terminal, return to the repository root and start the frontend. Its entry point is `frontend/src/main.tsx`.

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open [CitePath](http://127.0.0.1:5173/) and register a test account. The [API health endpoint](http://127.0.0.1:8000/api/health) checks whether the backend responds. The [model ping endpoint](http://127.0.0.1:8000/api/agent/ping) sends a request to the configured model provider.

The first PDF upload may trigger model downloads. To load the PDF parser and embedding model in advance, run `backend/.venv/bin/python tools/warm_model_cache.py` from the repository root.

## 3. Evaluation

The [evaluation guide](evaluation/README.md) specifies the browser procedures, expected outcomes, and recorded results. With the application running, execute the API acceptance suite from the repository root. It calls the configured model, creates a test account and course, and attempts to delete the course at the end.

```bash
backend/.venv/bin/python -B evaluation/verify_application.py --output evaluation/local-application.json
```

Run the following commands from the repository root to build the frontend, run the backend tests with MySQL coverage, and compare the two planning modes. The planner comparison uses a model double by default. The `--live` option calls the configured model and may incur charges.

```bash
(cd frontend && npm run build)
(cd backend && CITEPATH_SYNC_MYSQL_TESTS=1 .venv/bin/python -B -m unittest discover -s tests -v)
(cd backend && .venv/bin/python -B tools/evaluate_planner.py --output ../evaluation/local-planner-mock.json)
(cd backend && .venv/bin/python -B tools/evaluate_planner.py --live --output ../evaluation/local-planner-live.json)
```

## 4. Submission materials

- [Evaluation guide](evaluation/README.md) covers procedures, pass criteria, and execution records.
- [Access and configuration](submission/access-configuration.md) documents environment setup, limitations, and the location of runtime prompts.
- [AI use declaration](submission/ai-use-declaration.md) identifies the tools, models, and use cases.
- [Sample PDF sources and licenses](data/course-pdf-attribution.md) identifies the example inputs and their redistribution terms.
