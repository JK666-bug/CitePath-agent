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
