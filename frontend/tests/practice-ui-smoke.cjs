const assert = require('node:assert/strict')
const baseUrl = process.env.CITEPATH_UI_URL || (process.env.CITEPATH_UI_DIST ? 'http://citepath.test' : 'http://127.0.0.1:5174')
const { serveBuilt } = require('./serve-built.cjs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  await serveBuilt(page, process.env.CITEPATH_UI_DIST, baseUrl)
  const source = { document_id: 42, position: 1, filename: 'lecture.pdf', page_number: 7 }
  const round1 = { round_number: 1, correct_count: 0, total: 1, accuracy: 0, score: 0, passed: false, weak_concepts: ['Hashing'] }
  const round2 = { ...round1, round_number: 2 }
  let state = {
    id: 1, course_id: 1, chapter_id: 10, chapter_title: 'Hashing', status: 'open',
    phase: 'learn', round_number: 1, passing_threshold: 0.8, answered_count: 0,
    round_question_count: 1, round_results: [], feedback: null, report: null,
    concepts: [{ id: 8, name: 'Hashing', level: 0, streak: 0 }],
    question: { id: 11, concept_name: 'Hashing', kind: 'short', prompt: 'Explain hashing.', options: [], sources: [source], response: 'saved draft' },
  }
  let failGrading = true
  let failRoundGeneration = true
  let recordedQuestionId = 0
  let createdThreshold
  let examDraftPending = false
  let markDraftStarted
  let releaseDraft
  const draftStarted = new Promise((resolve) => { markDraftStarted = resolve })
  const draftReleased = new Promise((resolve) => { releaseDraft = resolve })
  let submittedExamAnswer
  let exam = {
    id: 5, course_id: 1, chapter_id: 10, chapter_title: 'Hashing exam', status: 'open',
    score: null, passed: null, report: null,
    questions: [{ id: 50, position: 1, concept_name: 'Hashing', kind: 'short', prompt: 'Explain the hash table.', options: [], sources: [source], response: '' }],
  }
  const calls = []
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/**', async (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const body = req.postData() ? JSON.parse(req.postData()) : null
    calls.push({ method: req.method(), path, body })
    let result
    if (path.endsWith('/documents/inventory')) result = require('./mock-inventory.cjs').inventoryOf([source])
    else if (path.endsWith('/exams/5/drafts')) {
      examDraftPending = true
      markDraftStarted()
      await draftReleased
      examDraftPending = false
      result = exam
    } else if (path.endsWith('/exams/5/submit')) {
      assert.equal(examDraftPending, false, 'earlier draft write must finish before submission')
      submittedExamAnswer = body.answers[0].response
      exam = { ...exam, status: 'finished', score: 100, passed: true, report: { score: 100, passed: true, correct_count: 1, total: 1, wrong_count: 0, wrong: [] } }
      result = exam
    } else if (path.endsWith('/exams/5')) result = exam
    else if (path === '/api/me') result = { id: 1, username: 'Tester' }
    else if (path === '/api/courses') result = { courses: [{ id: 1, name: 'Algorithms', student_brief: 'Study hashing', created_at: '2026-11-11', document_count: 1 }] }
    else if (path === '/api/courses/1/plan') result = { status: 'ready', plan: { version: 1, start: '2026-11-11', end: '2026-11-12', tasks: [], chapters: [{ id: '10', title: 'Hashing', concepts: ['Hashing'], sources: [source] }], reason: '' } }
    else if (path.endsWith('/practice/1/draft')) {
      assert.equal(req.method(), 'PATCH')
      if (body.question_id === recordedQuestionId) {
        return route.fulfill({ status: 400, json: { detail: 'Only the current unanswered question can be saved' } })
      }
      assert.equal(body.question_id, state.question.id)
      state.question.response = body.response
      result = { saved: true, question_id: body.question_id }
    } else if (path.endsWith('/practice/1/answer')) {
      state.question.response = body.response
      if (failGrading) {
        failGrading = false
        return route.fulfill({ status: 503, json: { detail: 'Could not grade this practice question' } })
      }
      if (state.round_number === 1) {
        recordedQuestionId = state.question.id
        if (failRoundGeneration) {
          failRoundGeneration = false
          state.round_results = [round1]
          return route.fulfill({ status: 503, json: { detail: 'Could not write a practice question. Try again.' } })
        }
        state = { ...state, phase: 'review', round_number: 2, round_results: [round1], feedback: { concept_name: 'Hashing', correct: false, explanation: 'Review the source page.', answer: 'A mapping from keys.', sources: [source] }, question: { id: 12, concept_name: 'Hashing', kind: 'mcq', prompt: 'Choose the hash property.', options: ['A property', 'Another property', 'Third', 'Fourth'], sources: [source], response: '' } }
      } else {
        state = { ...state, status: 'finished', question: null, report: { started_at: '2026-11-11 10:00', finished_at: '2026-11-11 10:02', question_count: 2, correct_count: 0, wrong_count: 2, concepts: [], wrong: [], questions: [], rounds: [round1, round2], passing_threshold: 0.8, passed: false, outcome: 'failed_after_2', remaining_weak_concepts: ['Hashing'], remaining_sources: [source] } }
      }
      result = state
    } else if (path.endsWith('/practice/1')) result = state
    else if (path.endsWith('/chapters/10/practice')) {
      createdThreshold = body.passing_threshold
      result = { ...state, id: 3 }
    } else if (path.endsWith('/practice/3')) result = state
    else return route.fulfill({ status: 404, json: { detail: `Unhandled mock ${path}` } })
    await route.fulfill({ json: result })
  })
  try {
    await page.goto(baseUrl + '/practice/1/sessions/1')
    await page.getByRole('heading', { name: 'Explain hashing.' }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'saved draft')
    await page.getByRole('button', { name: 'Doc 42 · p. 7', exact: true }).click()
    await page.getByText('Document 42 · Original PDF page 7', { exact: true }).waitFor()
    assert.equal(await page.getByRole('link', { name: 'Open original PDF at this page' }).getAttribute('href'), '/api/courses/1/documents/42/file#page=7')
    await page.getByRole('button', { name: 'Close dialog' }).click()

    await page.locator('textarea').fill('revised and saved answer')
    await page.getByText('Draft saved to your account.', { exact: false }).waitFor()
    await page.reload()
    await page.getByRole('heading', { name: 'Explain hashing.' }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'revised and saved answer')

    await page.locator('textarea').fill('latest answer before timer')
    await page.getByRole('button', { name: 'Submit answer', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'incomplete grading result' }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'latest answer before timer')
    await page.getByRole('button', { name: 'Submit answer', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'incomplete grading result' }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'latest answer before timer')
    assert.equal(await page.getByRole('heading', { name: 'Round results' }).count(), 0)
    await page.getByRole('button', { name: 'Submit answer', exact: true }).click()
    await page.getByRole('heading', { name: 'Choose the hash property.' }).waitFor()
    await page.getByText('Chapter practice · Round 2 of 2', { exact: true }).waitFor()
    await page.getByRole('heading', { name: 'Round results' }).waitFor()
    await page.getByRole('radio', { name: 'B Another property' }).check()
    await page.getByRole('button', { name: 'Submit answer', exact: true }).click()
    await page.getByText('Ended after round 2 · Not passed', { exact: true }).waitFor()
    assert.equal(await page.getByText('Round 1 of 2', { exact: true }).count(), 1)
    assert.equal(await page.getByText('Round 2 of 2', { exact: true }).count(), 1)
    assert.equal(await page.getByText(/Round 3/).count(), 0)
    assert.equal(await page.getByText('0%', { exact: true }).count(), 2)
    if (process.env.CITEPATH_SCREENSHOT) await page.screenshot({ path: process.env.CITEPATH_SCREENSHOT, fullPage: true })
    await page.getByRole('button', { name: 'Practice again', exact: true }).click()
    const startModal = page.getByRole('dialog', { name: 'Start practice', exact: true })
    await startModal.getByLabel('Chapter pass mark for a new session').selectOption('0.9')
    await startModal.getByRole('button', { name: 'Default chapter practice', exact: true }).click()
    await page.waitForURL('**/practice/1/sessions/3')
    assert.equal(createdThreshold, 0.9)

    await page.goto(baseUrl + '/exams/1/5')
    await page.getByRole('heading', { name: 'Explain the hash table.' }).waitFor()
    await page.locator('textarea').fill('older autosave answer')
    await draftStarted
    await page.locator('textarea').fill('latest submitted exam answer')
    await page.getByRole('button', { name: 'Submit exam', exact: true }).click()
    assert.equal(await page.locator('textarea').isDisabled(), true)
    releaseDraft()
    await page.waitForURL('**/exams/1/5/report')
    assert.equal(submittedExamAnswer, 'latest submitted exam answer')
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ result: 'PASS', checks: ['restored server draft', 'document id, original PDF page and authenticated file link', 'autosave and refresh', 'latest answer submitted', 'model failure retains answer and no score', 'retry after saved round1 and failed round2 generation', 'round 2 progress', 'independent round scores and final failure', 'new session threshold', 'exam autosave finishes before latest answer is submitted'], requests: calls.length }, null, 2))
  } finally {
    await browser.close()
  }
}
run().catch((error) => { console.error(error); process.exitCode = 1 })

