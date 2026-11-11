const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseUrl = process.env.CITEPATH_UI_URL || (process.env.CITEPATH_UI_DIST ? 'http://citepath.test' : 'http://127.0.0.1:5174')
const { serveBuilt } = require('./serve-built.cjs')
const copy = (value) => JSON.parse(JSON.stringify(value))

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } })
  await serveBuilt(page, process.env.CITEPATH_UI_DIST, baseUrl)
  const source = { document_id: 42, filename: 'lecture.pdf', page_number: 7 }
  const rubric = ['Keys select slots', 'Different keys may collide', 'Collisions need handling', 'Chaining uses buckets', 'Expected cost depends on assumptions']
  const failed = { explanation: '', explanation_status: 'failed', explanation_error: 'The explanation could not be generated. Retry the explanation.', explanation_attempts: 1 }
  const active = {
    id: 1, course_id: 1, chapter_id: 10, chapter_title: 'Hashing practice', status: 'open',
    phase: 'learn', round_number: 1, passing_threshold: .8, answered_count: 1, round_question_count: 2,
    round_results: [], report: null, concepts: [],
    question: { id: 12, concept_name: 'Hashing', kind: 'short', prompt: 'Explain the next concept.', options: [], sources: [source], response: 'server draft' },
    feedback: { question_id: 11, concept_name: 'Hashing', correct: false, answer: 'Different keys may share a slot.', sources: [source], ...failed,
      rubric, rubric_hits: [0, 1, 2], points_hit: 3, points_total: 5 },
  }
  const questions = [
    { question_id: 21, concept_name: 'Hash collisions', kind: 'short', phase: 'learn', round_number: 1,
      prompt: 'Explain why hashing can collide.', response: 'Incomplete explanation', answer: 'Two distinct keys can map to one slot.', sources: [source], correct: false,
      rubric, rubric_hits: [0, 1, 2], points_hit: 3, points_total: 5, ...failed },
    { question_id: 22, concept_name: 'Hashing', kind: 'mcq', phase: 'learn', round_number: 1,
      prompt: 'A correctly selected option.', response: 'A', answer: 'A', options: ['Correct option', 'Another', 'Third', 'Fourth'], sources: [source], correct: true,
      explanation: '', explanation_status: 'not_required', explanation_attempts: 0 },
    { question_id: 23, concept_name: 'Chaining', kind: 'short', phase: 'review', round_number: 2,
      prompt: 'Explain chaining from a legacy answer.', response: 'Incomplete older response', answer: 'Colliding entries use a bucket.', sources: [source], correct: false,
      explanation: 'Review the cited page.', rubric, rubric_hits: null, points_hit: 2, points_total: 5 },
  ]
  const report = {
    started_at: '2026-11-11 10:00', finished_at: '2026-11-11 10:02', question_count: 3, correct_count: 1, wrong_count: 2,
    rounds: [{ round_number: 1, correct_count: 1, total: 2, accuracy: .5, score: 50, passed: false, weak_concepts: ['Hash collisions'] },
             { round_number: 2, correct_count: 0, total: 1, accuracy: 0, score: 0, passed: false, weak_concepts: ['Chaining'] }],
    passing_threshold: .8, passed: false, outcome: 'failed_after_2', concepts: [], remaining_weak_concepts: ['Chaining'], remaining_sources: [source],
    questions, wrong: questions.filter((item) => !item.correct).map(copy),
    summary: 'This chapter session ended after two rounds. Feedback can be retried independently.',
    round_summaries: ['Round 1: 1 of 2 correct; the pass mark was not met.', 'Round 2: 0 of 1 correct; the pass mark was not met.'],
    review_guidance: [{ concept: 'Chaining', text: 'Re-read the cited page and compare your answer with the marking points.', sources: [source] }],
    feedback_pending_count: 2,
  }
  const finished = { ...active, id: 2, status: 'finished', phase: 'review', round_number: 2, question: null, feedback: null, report }
  const examQuestion = { id: 51, position: 1, concept_name: 'Chaining', kind: 'short', prompt: 'Explain the exam concept.', options: [], sources: [source],
    response: 'Incomplete answer', correct: false, answer: 'Colliding entries use a bucket.', rubric, rubric_hits: null, points_hit: 2, points_total: 5, ...failed }
  const exam = { id: 5, course_id: 1, chapter_id: 10, chapter_title: 'Hashing exam', status: 'finished', score: 50, passed: false,
    questions: [examQuestion, { ...examQuestion, id: 52, position: 2, kind: 'mcq', prompt: 'A correct exam option.', options: ['Correct', 'Other', 'Third', 'Fourth'], response: 'A', answer: 'A', correct: true, rubric: [], explanation: '', explanation_status: 'not_required', points_hit: 1, points_total: 1 }],
    report: { score: 50, passed: false, correct_count: 1, total: 2, wrong_count: 1, wrong: [{ ...examQuestion, question_id: 51 }],
      summary: 'This exam result is saved. Review the cited marking criteria.', round_summaries: [], review_guidance: [], feedback_pending_count: 1 } }
  const officialPractice = copy({ rounds: report.rounds, outcome: report.outcome, passed: report.passed, correct_count: report.correct_count,
    question_count: report.question_count, passing_threshold: report.passing_threshold, started_at: report.started_at, finished_at: report.finished_at })
  const checks = [], calls = [], errors = []
  let activeRetries = 0, examRetries = 0
  let retryStarted, releaseRetry
  const started = new Promise((resolve) => { retryStarted = resolve })
  const released = new Promise((resolve) => { releaseRetry = resolve })
  page.on('pageerror', (error) => errors.push(error.message))
  const ready = (attempts, text) => ({ explanation_status: 'ready', explanation_error: null, explanation_attempts: attempts, explanation: text })
  await page.route('**/api/**', async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname
    const body = request.postData() ? JSON.parse(request.postData()) : null
    calls.push({ path, method: request.method(), body })
    let result
    if (path === '/api/me') result = { id: 1, username: 'Tester' }
    else if (path === '/api/courses') result = { courses: [{ id: 1, name: 'Algorithms', student_brief: 'Study hashing', created_at: '2026-11-11', document_count: 1 }] }
    else if (path === '/api/courses/1/plan') result = { status: 'ready', plan: { version: 1, start: '2026-11-11', end: '2026-11-12', chapters: [{ id: '10', title: 'Hashing', concepts: ['Hashing'], sources: [source] }], tasks: [], reason: '' } }
    else if (path.endsWith('/practice/1/draft')) {
      assert.equal(body.question_id, 12)
      active.question.response = body.response
      result = { saved: true, question_id: 12 }
    } else if (path.endsWith('/practice/1/questions/11/explanation/retry')) {
      assert.equal(request.method(), 'POST')
      activeRetries++
      if (activeRetries === 1) {
        retryStarted()
        await released
        Object.assign(active.feedback, { ...failed, explanation_attempts: 2 })
      } else Object.assign(active.feedback, ready(3, 'Different keys can map to the same slot; see the cited page.'))
      result = active
    } else if (/\/practice\/2\/questions\/(21|23)\/explanation\/retry$/.test(path)) {
      const id = Number(path.match(/questions\/(\d+)/)[1])
      const fields = ready(2, `Source-based explanation recovered for question ${id}.`)
      for (const list of [report.questions, report.wrong]) for (const item of list) if (item.question_id === id) Object.assign(item, fields)
      report.feedback_pending_count--
      result = finished
    } else if (path.endsWith('/exams/5/questions/51/explanation/retry')) {
      examRetries++
      const fields = examRetries === 1 ? { ...failed, explanation_attempts: 2 } : ready(3, 'Recovered exam explanation from the cited page.')
      Object.assign(exam.questions[0], fields)
      Object.assign(exam.report.wrong[0], fields)
      exam.report.feedback_pending_count = examRetries === 1 ? 1 : 0
      result = exam
    } else if (path.endsWith('/practice/1')) result = active
    else if (path.endsWith('/practice/2')) result = finished
    else if (path.endsWith('/exams/5')) result = exam
    else throw new Error(`Unexpected API call during explanation recovery: ${request.method()} ${path}`)
    await route.fulfill({ json: copy(result) })
  })

  try {
    await page.goto(baseUrl + '/practice/1/sessions/1')
    await page.getByRole('heading', { name: 'Explain the next concept.' }).waitFor()
    await page.getByText('Explanation unavailable.', { exact: true }).waitFor()
    assert.equal(await page.getByText('Matched', { exact: true }).count(), 3)
    checks.push('active feedback shows failed status and actual rubric matches')
    await page.locator('textarea').fill('unsaved next-question draft survives feedback retry')
    await page.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await started
    assert.equal(await page.locator('textarea').isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: 'Retrying explanation…' }).isDisabled(), true)
    releaseRetry()
    await page.getByText('2 generation attempts', { exact: true }).waitFor()
    await page.getByText('Explanation unavailable.', { exact: true }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'unsaved next-question draft survives feedback retry')
    checks.push('HTTP 200 with failed explanation stays retryable and preserves the unsaved draft')
    await page.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await page.getByText('Different keys can map to the same slot; see the cited page.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Retry explanation', exact: true }).count(), 0)
    assert.equal(await page.locator('textarea').inputValue(), 'unsaved next-question draft survives feedback retry')
    await page.locator('p.practice-save-status').filter({ hasText: 'Draft saved to your account.' }).waitFor()
    await page.reload()
    await page.getByRole('heading', { name: 'Explain the next concept.' }).waitFor()
    assert.equal(await page.locator('textarea').inputValue(), 'unsaved next-question draft survives feedback retry')
    assert.equal(await page.getByRole('button', { name: 'Retry explanation', exact: true }).count(), 0)
    assert.equal(active.round_number, 1)
    assert.equal(active.question.id, 12)
    checks.push('successful explanation retry survives refresh without grading the next question')

    await page.goto(baseUrl + '/practice/1/sessions/2')
    await page.getByRole('heading', { name: 'Chapter summary', exact: true }).waitFor()
    await page.getByText(report.summary, { exact: true }).waitFor()
    await page.getByText(report.round_summaries[0], { exact: true }).waitFor()
    await page.getByRole('heading', { name: 'Review guidance', exact: true }).waitFor()
    checks.push('chapter narrative and per-round explanations render with source-bearing review guidance')
    const failedArticle = page.locator('article').filter({ hasText: 'Explain why hashing can collide.' })
    const legacyArticle = page.locator('article').filter({ hasText: 'Explain chaining from a legacy answer.' })
    const correctArticle = page.locator('article').filter({ hasText: 'A correctly selected option.' })
    assert.equal(await failedArticle.getByText('Matched', { exact: true }).count(), 3)
    assert.equal(await failedArticle.getByText('Not matched', { exact: true }).count(), 2)
    await legacyArticle.getByText('Individual point matches were not recorded for this answer.', { exact: true }).waitFor()
    assert.equal(await legacyArticle.getByText('Matched', { exact: true }).count(), 0)
    assert.equal(await correctArticle.getByRole('button', { name: 'Retry explanation', exact: true }).count(), 0)
    assert.equal(await legacyArticle.getByText('Review the cited page.', { exact: true }).count(), 0)
    checks.push('legacy placeholder is pending, unknown rubric hits stay unknown, and correct answers have no remedial retry')
    await failedArticle.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await failedArticle.getByText('Source-based explanation recovered for question 21.', { exact: true }).waitFor()
    await legacyArticle.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await legacyArticle.getByText('Source-based explanation recovered for question 23.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Retry explanation', exact: true }).count(), 0)
    assert.equal(await page.getByText('50%', { exact: true }).count(), 1)
    assert.equal(await page.getByText('0%', { exact: true }).count(), 1)
    for (const [name, value] of Object.entries(officialPractice)) assert.deepEqual(report[name], value)
    await page.reload()
    await page.getByText('Source-based explanation recovered for question 23.', { exact: true }).waitFor()
    assert.equal(await page.getByText(/Round 3/).count(), 0)
    checks.push('finished feedback recovery preserves both official round results, timestamps and final outcome across refresh')
    if (process.env.CITEPATH_FEEDBACK_SCREENSHOT) await page.screenshot({ path: process.env.CITEPATH_FEEDBACK_SCREENSHOT, fullPage: true })

    await page.goto(baseUrl + '/exams/1/5/report')
    await page.getByText(exam.report.summary, { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await page.getByText('2 generation attempts', { exact: true }).waitFor()
    await page.getByText('Explanation unavailable.', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Retry explanation', exact: true }).click()
    await page.getByText('Recovered exam explanation from the cited page.', { exact: true }).waitFor()
    assert.equal(exam.score, 50)
    assert.equal(exam.passed, false)
    assert.equal(exam.questions[0].correct, false)
    assert.equal(exam.questions[1].correct, true)
    await page.reload()
    await page.getByText('Recovered exam explanation from the cited page.', { exact: true }).waitFor()
    assert.equal(await page.getByText('50%', { exact: true }).count(), 1)
    checks.push('exam explanation failure and recovery retain the official score, answer grades and report after refresh')
    assert.equal(calls.filter((call) => /\/(answer|submit)$/.test(call.path)).length, 0)
    assert.equal(calls.filter((call) => call.method === 'POST' && !call.path.endsWith('/explanation/retry')).length, 0)
    assert.deepEqual(errors, [])
    checks.push('explanation retries cause no scoring or question-generation requests and no browser errors')
    console.log(JSON.stringify({ result: 'PASS', checks, requests: calls.length, mode: 'mocked_api_browser' }, null, 2))
  } finally { await browser.close() }
}

run().catch((error) => { console.error(error); process.exitCode = 1 })
