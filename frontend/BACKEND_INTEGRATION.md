# CitePath Frontend and API Integration

The React application sends relative `/api` requests through the Vite development proxy to FastAPI. The backend manages MySQL, Milvus, PDF processing, and the configured model provider. Model credentials are configured on the backend. [Vite configuration](vite.config.ts) · [Backend entry point](../backend/main.py) · [Access and configuration](../submission/access-configuration.md)

## Request and session handling

`src/shared/request.ts` includes session cookies with API requests and converts errors to messages for the interface. Registration and sign-in establish a session. The application calls `GET /api/me` when it starts and returns to sign-in when an authenticated request reports an expired session.

## Main workflows

| Workflow | Representative API calls |
| --- | --- |
| Accounts and courses | `POST /api/register`, `POST /api/login`, `GET /api/courses`, `POST /api/courses` |
| Material ingestion and chapter analysis | `POST /api/courses/{course_id}/documents`, `GET /api/courses/{course_id}/chapters/options`, `POST /api/courses/{course_id}/chapters/rebuild` |
| Schedule review and publication | `PUT /api/courses/{course_id}/settings`, `POST /api/courses/{course_id}/schedule`, `POST /api/courses/{course_id}/schedule/{run_id}/apply` |
| Reading and course Q&A | `GET /api/courses/{course_id}/documents/{document_id}/file`, `POST /api/courses/{course_id}/questions` |
| Practice and exam generation | `POST /api/courses/{course_id}/chapters/{chapter_id}/practice`, `POST /api/courses/{course_id}/chapters/{chapter_id}/exams` |

Schedule preview and publication are separate operations. The application reviews a proposed schedule before applying it to the calendar. If the preview no longer matches the course state, the API rejects publication and the interface requests a new preview.

The example course under `/courses/demo` uses browser-local demonstration data. To verify PDF ingestion, persistence, and model-assisted workflows, create a regular course and follow the [evaluation guide](../evaluation/README.md). For the API schemas, open [FastAPI documentation](http://127.0.0.1:8000/docs) after starting the backend.
