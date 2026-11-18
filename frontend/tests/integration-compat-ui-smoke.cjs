const assert = require('node:assert/strict')
const { serveBuilt } = require('./serve-built.cjs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseUrl = process.env.CITEPATH_UI_URL || (process.env.CITEPATH_UI_DIST ? 'http://citepath.test' : 'http://127.0.0.1:5174')

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1050 } })
    page.setDefaultTimeout(10000)
    await serveBuilt(page, process.env.CITEPATH_UI_DIST, baseUrl)
    const errors = [], calls = []
    page.on('pageerror', error => errors.push(error.message))
    const source = { document_id: 42, filename: 'hashing.pdf', page_number: 7 }
    const profile = { goal: 'Learn hashing', prior_knowledge: 'Basic algorithms', daily_minutes: 45, reading_words_per_minute: 180 }
    const plan = { version: 1, start: '2026-11-18', end: '2026-11-19', reason: 'Saved plan', planning_profile: profile,
      chapters: [{ id: '10', title: 'Hashing', concepts: ['Hashing'], sources: [source] }],
      tasks: [{ id: 'read-10', chapterId: '10', title: 'Read hashing', kind: 'Reading', status: 'Not started', date: '2026-11-18', concepts: ['Hashing'], sources: [source] }] }
    const docs = [42, 67].map((id, i) => ({ id, filename: i ? 'trees.pdf' : 'hashing.pdf', position: i + 1, ingest_status: 'complete', page_count: 10, usable_page_count: 10, has_file: true }))
    const course = { id: 1, name: 'Algorithms', created_at: '2026-11-18', student_brief: 'Keep saved work', documents: docs }
    const examCase = { id: 50, position: 1, filename: 'sample-case.pdf', ingest_status: 'complete', usable_page_count: 2, page_count: 2, answer_mode: 'file', answer_file: { id: 51, filename: 'sample-answer.pdf', ingest_status: 'complete', page_count: 1, usable_page_count: 1 } }
    let qa = [], uploaded = false, allArchived = false
    const activeSession = { id: 7, course_id: 1, chapter_id: 10, chapter_title: 'Hashing', status: 'open', phase: 'learn', round_number: 1, passing_threshold: .7, round_results: [], concepts: [], report: null, feedback: null,
      question: { id: 71, concept_name: 'Hashing', kind: 'short', prompt: 'Explain hashing.', sources: [source], options: [] } }
    await page.route('**/api/**', async route => {
      const req = route.request(), path = new URL(req.url()).pathname
      const json = req.headers()['content-type']?.includes('application/json') ? req.postDataJSON() : null
      calls.push({ path, method: req.method(), body: json })
      let result
      if (path === '/api/me') result = { id: 1, username: 'Integration reviewer' }
      else if (path === '/api/courses') result = { courses: [{ ...course, document_count: 2 }] }
      else if (path === '/api/courses/1') result = { ...course, documents: allArchived ? [] : docs }
      else if (path === '/api/courses/1/plan') result = { status: 'ready', plan, material_update: { new_page_count: allArchived ? 0 : 10, new_document_ids: allArchived ? [] : [67], missing_document_ids: allArchived ? [42] : [], can_update: !allArchived } }
      else if (path === '/api/courses/1/exam-cases' && req.method() === 'GET') result = { cases: [examCase] }
      else if (path === '/api/courses/1/exam-cases' && req.method() === 'POST') {
        const body = req.postData()
        assert.match(body, /name="answer_mode"\r\n\r\nfile/)
        assert.match(body, /filename="new-case.pdf"/)
        assert.match(body, /filename="new-answer.pdf"/)
        uploaded = true
        result = { document_id: 52, filename: 'new-case.pdf', duplicate: false, page_count: 1, usable_page_count: 1, answer_mode: 'file' }
      }
      else if (path === '/api/courses/1/chapters/10/practice' || path === '/api/courses/1/practice/7') result = activeSession
      else if (path === '/api/courses/1/questions' && req.method() === 'GET') result = qa
      else if (path === '/api/courses/1/questions') {
        const response = { qa_id: qa.length + 1, course_name: 'Algorithms', question: json.question, answer: 'Saved casual reply.', cited_pages: [], refused: false, origin: 'chat', tab_id: json.tab_id, tab_title: 'Casual chat' }
        qa.push(response)
        result = response
      } else if (path === '/api/courses/1/notes') return route.fulfill({ contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="integration-notes.pdf"' }, body: '%PDF-1.4\n% Mock download only\n' })
      else if (path.endsWith('/file')) return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n% Mock original only\n' })
      else return route.fulfill({ status: 404, json: { detail: 'Unexpected mocked path' } })
      await route.fulfill({ json: result })
    })

    await page.goto(baseUrl + '/practice?course=1')
    await page.getByRole('button', { name: 'Practice', exact: true }).click()
    const modal = page.getByRole('dialog', { name: 'Start practice', exact: true })
    await modal.getByLabel('Chapter pass mark for a new session').selectOption('0.7')
    await modal.getByRole('button', { name: 'Custom practice', exact: true }).click()
    await modal.getByLabel('Requirements', { exact: true }).fill('Emphasize collisions')
    await modal.getByLabel('Difficulty').selectOption('hard')
    await modal.getByLabel('Preferred question style').selectOption('short')
    await modal.getByLabel('Question density hint', { exact: false }).fill('12')
    await modal.getByLabel('Match exam-case style', { exact: true }).check()
    await modal.getByLabel('sample-case.pdf', { exact: true }).check()
    await modal.getByRole('button', { name: 'Start custom practice', exact: true }).click()
    await page.waitForURL('**/practice/1/sessions/7')
    const practice = calls.find(call => call.path.endsWith('/chapters/10/practice')).body
    assert.deepEqual(practice, { passing_threshold: .7, requirements: 'Emphasize collisions', difficulty: 'hard', similar_to_cases: true, preferred_kind: 'short', question_count: 12, case_document_ids: [50] })
    await page.getByText('Chapter practice · Round 1 of 2', { exact: true }).waitFor()

    await page.goto(baseUrl + '/courses/1/plan')
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).waitFor()
    assert.equal(await page.locator('.document-picker').count(), 0)
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).click()
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).waitFor()
    const planCall = calls.find(call => call.path.endsWith('/plan') && call.method === 'POST').body
    assert.equal(planCall.document_ids, undefined)
    assert.deepEqual(planCall.profile, profile)
    assert.equal(planCall.expected_version, 1)
    assert.equal(planCall.update_materials, false)
    await page.getByLabel('Include new materials when updating this plan', { exact: true }).check()
    await page.getByText('New PDFs to append', { exact: true }).waitFor()
    assert.equal(await page.locator('.document-picker').getByLabel('hashing.pdf', { exact: false }).count(), 0)
    await page.getByRole('button', { name: 'Clear', exact: true }).click()
    await page.getByRole('button', { name: 'Include new materials and update plan', exact: true }).click()
    await page.getByRole('alert').getByText('Select at least one PDF.', { exact: true }).waitFor()
    await page.locator('.document-picker').getByLabel('trees.pdf', { exact: false }).check()
    await page.getByRole('button', { name: 'Include new materials and update plan', exact: true }).click()
    await page.getByRole('button', { name: 'Include new materials and update plan', exact: true }).waitFor()
    const append = calls.filter(call => call.path.endsWith('/plan') && call.method === 'POST').at(-1).body
    assert.deepEqual(append.document_ids, [67])
    assert.deepEqual(append.profile, profile)
    assert.equal(append.expected_version, 1)
    assert.equal(append.update_materials, true)
    allArchived = true
    await page.goto(baseUrl + '/courses/1/plan')
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).waitFor()
    assert.equal(await page.locator('.document-picker').count(), 0)
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).click()
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).waitFor()
    const archived = calls.filter(call => call.path.endsWith('/plan') && call.method === 'POST').at(-1).body
    assert.equal(archived.document_ids, undefined)
    assert.equal(archived.update_materials, false)
    allArchived = false

    await page.goto(baseUrl + '/courses/1/qa')
    await page.getByTitle('Choose PDFs for this answer').click()
    const selection = page.getByRole('dialog', { name: 'PDF selection', exact: true })
    await selection.getByRole('button', { name: 'Clear', exact: true }).click()
    await page.getByTitle('Choose PDFs for this answer').click()
    await page.getByText('No PDF selected — casual chat. Turn on Web to search online.', { exact: true }).waitFor()
    await page.locator('.qa-composer-input').fill('Hello without lecture retrieval')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await page.locator('.qa-thread').getByText('Saved casual reply.', { exact: true }).waitFor()
    const qaCall = calls.find(call => call.path.endsWith('/questions') && call.method === 'POST').body
    assert.deepEqual(qaCall.document_ids, [])
    assert.ok(qaCall.tab_id)
    await page.reload()
    await page.locator('.qa-thread').getByText('Saved casual reply.', { exact: true }).waitFor()

    await page.goto(baseUrl + '/courses/1/read?task=read-10')
    await page.getByRole('heading', { name: 'Read hashing', exact: true }).waitFor()
    assert.equal(await page.locator('iframe[title="hashing.pdf"]').getAttribute('src'), '/api/courses/1/documents/42/file#page=7')

    await page.goto(baseUrl + '/courses/1/notes')
    await page.getByRole('button', { name: 'Clear', exact: true }).click()
    await page.locator('.document-picker').getByLabel('hashing.pdf', { exact: false }).check()
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Generate study notes PDF', exact: true }).click()
    assert.equal((await download).suggestedFilename(), 'integration-notes.pdf')
    assert.deepEqual(calls.find(call => call.path.endsWith('/notes')).body.document_ids, [42])

    await page.goto(baseUrl + '/courses/1/cases')
    await page.getByText('Answer file: sample-answer.pdf', { exact: false }).waitFor()
    await page.getByLabel('Exam-case PDF', { exact: true }).setInputFiles({ name: 'new-case.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nMock') })
    await page.getByLabel('Separate answer PDF', { exact: true }).check()
    await page.getByLabel('Answer PDF', { exact: true }).setInputFiles({ name: 'new-answer.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nMock') })
    await page.getByRole('button', { name: 'Upload exam case', exact: true }).click()
    await page.getByText('Exam case saved. It can guide practice and exams when you choose that option.', { exact: true }).waitFor()
    assert.equal(uploaded, true)
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ result: 'PASS', mode: 'mocked_api_browser', checks: [
      'custom practice combines saved pass mark, prefs and selected sample cases while retaining round 1 of 2',
      'rescheduling works with all PDFs archived; explicit append selects only new PDFs and retains profile/version',
      'explicit empty QA selection enables casual chat with persistent conversation ID',
      'reading uses stable existing PDF ID and original page',
      'notes downloads PDF using selected lectures',
      'sample exam upload includes a separate answer file and no browser errors',
    ] }, null, 2))
  } finally { await browser.close() }
}
run().catch(error => { console.error(error); process.exitCode = 1 })
