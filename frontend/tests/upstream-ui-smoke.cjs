const assert = require('node:assert/strict')
const { serveBuilt } = require('./serve-built.cjs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseUrl = process.env.CITEPATH_UI_URL || (process.env.CITEPATH_UI_DIST ? 'http://citepath.test' : 'http://127.0.0.1:5174')

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } })
    const errors = [], mutations = []
    page.on('pageerror', e => errors.push(e.message))
    await serveBuilt(page, process.env.CITEPATH_UI_DIST, baseUrl)
    const source = { document_id: 42, position: 1, filename: 'hashing.pdf', page_number: 3 }
    const course = { id: 1, name: 'Algorithms', student_brief: JSON.stringify({ schema: 'citepath-course-v1', deadline: '2026-12-01', earlyDays: 0, note: 'Review algorithms' }), created_at: '2026-11-12', documents: [
      { id: 42, position: 1, filename: 'hashing.pdf', ingest_status: 'complete', page_count: 5, usable_page_count: 4 },
      { id: 79, position: 2, filename: 'trees.pdf', ingest_status: 'failed', ingest_error: 'Vector indexing failed. Retry the same PDF.', page_count: 6, usable_page_count: 5 },
    ] }
    let records = [
      { qa_id: 3, course_id: 1, course_name: 'Algorithms', question: 'Earlier tree question', answer: 'Earlier tree answer.', refused: false, cited_pages: [source], web_sources: [] },
      { qa_id: 8, course_id: 1, course_name: 'Algorithms', question: 'Latest hash question', answer: 'Latest hash answer.', refused: false, cited_pages: [source], web_sources: [] },
    ]
    await page.route('**/api/**', async route => {
      const req = route.request(), path = new URL(req.url()).pathname
      let result
      if (req.method() !== 'GET') mutations.push(path)
      if (path.endsWith('/documents/inventory')) result = require('./mock-inventory.cjs').inventoryOf([source])
      else if (path === '/api/me') result = { id: 1, username: 'Reviewer' }
      else if (path === '/api/courses') result = { courses: [{ ...course, document_count: 2 }] }
      else if (path === '/api/courses/1') result = course
      else if (path === '/api/courses/1/plan') result = { status: 'draft', plan: null }
      else if (path === '/api/courses/1/questions' && req.method() === 'GET') result = records
      else if (path === '/api/courses/1/questions') {
        const body = req.postDataJSON()
        const row = { ...records[1], qa_id: 9, question: body.question, answer: 'New saved answer.', tab_id: body.tab_id, tab_title: 'Earlier tree question' }
        assert.deepEqual(body.document_ids, [42])
        records = [...records, row]
        result = row
      } else return route.fulfill({ status: 404, json: { detail: 'Unexpected mock request' } })
      await route.fulfill({ json: result })
    })
    await page.goto(baseUrl + '/courses/1/qa')
    await page.getByRole('heading', { name: 'Chats' }).waitFor()
    const answer = page.locator('.qa-thread')
    assert.match(await answer.textContent(), /Latest hash answer/)
    await page.locator('.qa-history-open').filter({ hasText: 'Earlier tree question' }).click()
    assert.match(await answer.textContent(), /Earlier tree answer/)
    await answer.getByRole('button', { name: /Doc 42/ }).click()
    const pdf = page.getByRole('link', { name: /Open original PDF/ })
    assert.equal(await pdf.getAttribute('href'), '/api/courses/1/documents/42/file#page=3')
    await page.getByRole('button', { name: 'Close dialog' }).click()
    await page.locator('textarea').fill('Another hash question')
    await page.locator('.qa-question').getByRole('button', { name: 'Send', exact: true }).click()
    await answer.getByText('New saved answer.', { exact: true }).waitFor()
    await page.reload()
    await page.locator('.qa-thread').getByText('New saved answer.', { exact: true }).waitFor()
    await page.goto(baseUrl + '/courses/1/info')
    assert.equal(await page.getByRole('link', { name: 'hashing.pdf', exact: true }).getAttribute('href'), '/api/courses/1/documents/42/file')
    assert.equal(await page.getByRole('link', { name: 'trees.pdf', exact: true }).getAttribute('href'), '/api/courses/1/documents/79/file')
    assert.match(await page.locator('.materials-list').textContent(), /Vector indexing failed/)
    assert.deepEqual(mutations, ['/api/courses/1/questions'])
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ result: 'PASS', mode: 'mocked_api_browser', checks: [
      'Q&A tabs select the newest conversation and load legacy rows', 'selecting earlier history shows its answer',
      'citation retains stable document ID and original page after numbering changes',
      'new answer is selected and survives refresh', 'PDF links and ingestion retry errors remain available',
      'Q&A and history issue no practice-scoring requests',
    ] }, null, 2))
  } finally { await browser.close() }
}
run().catch(error => { console.error(error); process.exitCode = 1 })
