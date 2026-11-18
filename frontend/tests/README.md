# Practice and exam UI smoke test

This test uses mocked API responses. It checks browser behavior without MySQL,
Milvus, lecture files, or model credentials; it does not validate those services.

Install the frontend dependencies and Playwright, then start the Vite server:

```powershell
npm ci
npm install --no-save playwright
npm run dev -- --host 127.0.0.1 --port 5174
```

In another terminal, from `frontend`:

```powershell
node tests/practice-ui-smoke.cjs
node tests/feedback-ui-smoke.cjs
node tests/upstream-ui-smoke.cjs
node tests/planning-ui-smoke.cjs
node tests/integration-compat-ui-smoke.cjs
```

Google Chrome must be installed. To use an installed Microsoft Edge instead,
set `$env:CITEPATH_BROWSER = 'msedge'` before running the test.
`CITEPATH_UI_URL` overrides the server URL. `CITEPATH_SCREENSHOT` optionally
saves a full-page report screenshot. A preinstalled Playwright package can be
selected using `PLAYWRIGHT_MODULE` (its package directory).

The test covers saved-draft restoration, autosave and refresh, document IDs and
original PDF page links, incomplete model grading, retry after round-one scoring
and round-two generation failure, the two-round limit and separate scores, the
new-session pass mark, and an older exam draft finishing before the latest
submission. Success prints `PASS`; failed checks exit with a nonzero code.

The feedback smoke test additionally covers a saved grade whose explanation is
unavailable, a retry returning HTTP 200 with another failed explanation, successful
recovery and refresh, unchanged next-question drafts, fixed round results and exam
grades, legacy placeholder feedback, report prose, and actual versus unknown rubric
point matches. Correct answers never offer a remedial explanation retry. These
checks verify UI behavior using mocked responses; they do not measure model quality.

`CITEPATH_FEEDBACK_SCREENSHOT` optionally saves the completed practice report
from the feedback smoke test. Both scripts use the same server and browser settings.

To test the production build without opening a local HTTP server, run the build
and set `CITEPATH_UI_DIST` to its directory. Playwright serves these files directly
from disk and continues to mock the API; it makes no application network requests:

```powershell
npm run build
$env:CITEPATH_UI_DIST = 'dist'
node tests/practice-ui-smoke.cjs
node tests/feedback-ui-smoke.cjs
node tests/upstream-ui-smoke.cjs
node tests/planning-ui-smoke.cjs
node tests/integration-compat-ui-smoke.cjs
```

The upstream smoke verifies Q&A history, stable document-ID/page links after display
renumbering, saved answers after refresh, and Q&A isolation from practice mutations.
The planning smoke verifies incomplete-profile questions, estimates and daily
budgets, explicit incremental material updates, preserved completed tasks/reports,
read-only version viewing, failure retry, version conflict recovery, plain-text
legacy preferences and mobile layout. The original four scripts cover 36 mocked
browser checks; they do not establish actual API or model performance.

`node tests/restoration-ui-smoke.cjs` adds eight checks for archived/missing original
sources, failed restore/retry, stable IDs, explicit archive wording and unchanged
practice state. All five scripts use mocked APIs; the total is 44 browser checks.

`node tests/integration-compat-ui-smoke.cjs` adds six checks for the November 18
integration: custom practice combines the fixed pass mark and sample-case preferences;
plan PDF selection retains profile, version and incremental-update settings; explicit
empty QA selection stays casual chat; the reading page uses stable original PDF IDs;
notes download uses selected lectures; and sample-case upload includes a separate
answer PDF. The six suites total 50 mocked browser checks. The Q&A suite covers
conversation tabs, including legacy rows without a tab ID. These checks do not call
a real model, database or vector service.

## Read-only browser acceptance against actual services

`node tests/live-ui-smoke.cjs` uses the real frontend/API and a previously completed
dedicated development integration fixture. It does not mock API responses, create
practice, grade answers, ask a new question or retry explanations. Start the actual
API on port 8000 and Vite on port 5173; the existing Vite proxy forwards `/api`.

Set these environment variables before running:

- `CITEPATH_LIVE_CREDENTIALS_FILE`: a local private JSON file with `username` and
  `password` for the dedicated `citepath_it_...` development account. Never commit
  it. `CITEPATH_INTEGRATION_USERNAME` / `CITEPATH_INTEGRATION_PASSWORD` keys are also
  accepted in that JSON file.
- `CITEPATH_LIVE_REPORT_FILE`: the real backend integration report containing
  `resources.user_id`, `course_id` and `practice_session_id`. The saved practice
  must be finished; a generated plan, plan snapshot and Q&A history must exist.
- `CITEPATH_UI_URL`: local frontend origin, default `http://127.0.0.1:5173`.
- Optional `CITEPATH_LIVE_OUTPUT`: report JSON path; credentials, cookies, request
  bodies, raw Playwright error text and page HTML are not exported.
- Optional `CITEPATH_LIVE_SCREENSHOT_DIR`: directory for authenticated desktop and
  mobile screenshots. Password inputs are masked; model-service keys are never
  loaded into this test.

`PLAYWRIGHT_MODULE` and `CITEPATH_BROWSER` behave like the mocked smoke suites.
This verifies actual login, plan/history/source/report rendering, PDF identity,
refresh, Q&A history and read-only invariants. It is separate from human grading,
citation-support review and the formal baseline/full evaluation.
