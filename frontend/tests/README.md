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
