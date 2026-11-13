/* Real API/browser acceptance on a retained, dedicated development fixture.
 * No API mocking, model submission, material change, scoring or new practice.
 * Credentials are loaded only from a local file and are never reported.
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

const baseUrl = process.env.CITEPATH_UI_URL || 'http://127.0.0.1:5173'
const output = process.env.CITEPATH_LIVE_OUTPUT
const shots = process.env.CITEPATH_LIVE_SCREENSHOT_DIR
const result = {
  schema: 'citepath-live-ui-smoke-v1',
  started_at: new Date().toISOString(),
  status: 'running',
  mode: 'real_api_browser_read_only',
  synthetic: false,
  api_mocking: false,
  model_invoked_by_this_test: false,
  official_accepted: null,
  checks: [],
  requests: [],
  limits: ['Uses existing finished development data; does not replace formal model quality or human annotation.'],
}
let phase = 'configuration'
let browser
let currentPage

function stable(value) {
  if (Array.isArray(value)) return value.map(stable)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]))
  return value
}
function fingerprint(value) {
  return crypto.createHash('sha256').update(JSON.stringify(stable(value))).digest('hex')
}
function gradeSnapshot(state) {
  return fingerprint({ id: state.id, status: state.status, round_number: state.round_number,
    passing_threshold: state.passing_threshold, round_results: state.round_results, report: state.report })
}
function save() {
  if (output) {
    fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true })
    fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n', 'utf8')
  }
}
function passed(name, detail) {
  result.checks.push({ name, passed: true, ...(detail ? { detail } : {}) })
  save()
}
async function json(request, pathname) {
  const response = await request.get(pathname)
  assert.equal(response.status(), 200, 'Expected real API HTTP 200')
  return response.json()
}
async function navigate(page, pathname) {
  await page.goto(baseUrl + pathname)
  await page.waitForLoadState('networkidle')
}
async function screenshot(page, name) {
  if (!shots) return
  fs.mkdirSync(shots, { recursive: true })
  await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: true,
    mask: [page.locator('input[type="password"]')] })
}

async function run() {
  const origin = new URL(baseUrl)
  assert(['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname), 'Only a local frontend is accepted')
  assert(!origin.username && !origin.password && !origin.search && !origin.hash, 'Use a plain local origin')
  assert(process.env.CITEPATH_LIVE_CREDENTIALS_FILE, 'Set CITEPATH_LIVE_CREDENTIALS_FILE')
  assert(process.env.CITEPATH_LIVE_REPORT_FILE, 'Set CITEPATH_LIVE_REPORT_FILE')
  const credentials = JSON.parse(fs.readFileSync(process.env.CITEPATH_LIVE_CREDENTIALS_FILE, 'utf8').replace(/^\uFEFF/, ''))
  const fixture = JSON.parse(fs.readFileSync(process.env.CITEPATH_LIVE_REPORT_FILE, 'utf8').replace(/^\uFEFF/, ''))
  assert.equal(fixture.schema, 'citepath-live-integration-v1', 'Use a real development integration report')
  assert.equal(fixture.synthetic, false, 'Synthetic fixtures cannot establish actual UI/model integration')
  assert(fixture.checks?.some((check) => check.name === 'real_plan_generated' && check.status === 'passed'),
    'The integration report must record a successful real model-generated plan')
  const username = credentials.username || credentials.CITEPATH_INTEGRATION_USERNAME
  const password = credentials.password || credentials.CITEPATH_INTEGRATION_PASSWORD
  assert(typeof username === 'string' && username.startsWith('citepath_it_'), 'Use an explicitly dedicated development account')
  assert(typeof password === 'string' && password.length >= 6, 'Dedicated development password is required')
  const courseId = Number(fixture.resources?.course_id)
  const sessionId = Number(fixture.resources?.practice_session_id)
  assert(Number.isSafeInteger(courseId) && courseId > 0 && Number.isSafeInteger(sessionId) && sessionId > 0,
    'The real integration report must contain course and practice IDs')
  result.resources = { course_id: courseId, practice_session_id: sessionId }

  browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1360, height: 980 } })
  currentPage = page
  page.setDefaultTimeout(20000)
  const pageErrors = []
  const businessMutations = []
  let authenticated = false
  const badResponses = []
  result.browser_error_types = pageErrors
  result.authenticated_http_errors = badResponses
  page.on('pageerror', (error) => pageErrors.push(error.name || 'Error'))
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) return
    const method = request.method()
    result.requests.push({ method, path: url.pathname })
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !['/api/login', '/api/logout'].includes(url.pathname)) {
      businessMutations.push({ method, path: url.pathname })
    }
  })
  page.on('response', (response) => {
    const pathname = new URL(response.url()).pathname
    if (authenticated && pathname.startsWith('/api/') && response.status() >= 400) {
      badResponses.push({ path: pathname, status: response.status() })
    }
  })

  phase = 'real_login'
  await navigate(page, '/login')
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL('**/courses')
  await page.waitForLoadState('networkidle')
  authenticated = true
  const me = await json(page.request, baseUrl + '/api/me')
  assert.equal(me.username, username)
  assert.equal(Number(me.id), Number(fixture.resources.user_id))
  passed('real_ui_login_and_owner_identity')

  const base = `/api/courses/${courseId}`
  const course = await json(page.request, baseUrl + base)
  const initialPlan = await json(page.request, baseUrl + base + '/plan')
  const initialState = await json(page.request, baseUrl + base + `/practice/${sessionId}`)
  assert.equal(initialState.status, 'finished', 'Read-only UI smoke requires an already finished practice')
  assert(initialState.report && initialState.round_results?.length, 'An actual finished report is required')
  assert(initialPlan.plan?.chapters?.length, 'An actual generated plan is required')
  const chapterId = Number(initialState.chapter_id)
  result.resources.chapter_id = chapterId
  const initialGrade = gradeSnapshot(initialState)
  const initialPlanHash = fingerprint(initialPlan.plan)
  const initialVersions = await json(page.request, baseUrl + base + '/plan/versions')
  passed('actual_finished_session_and_generated_plan_available')

  phase = 'course_information'
  await navigate(page, `/courses/${courseId}/info`)
  await page.getByRole('heading', { level: 1, name: course.name, exact: true }).waitFor()
  const inventory = await json(page.request, baseUrl + base + '/documents/inventory')
  const active = inventory.documents.filter((document) => document.active)
  assert(active.length > 0)
  for (const document of active) {
    await page.getByRole('link', { name: document.filename, exact: true }).waitFor()
    await page.getByText(new RegExp(`Document ID ${document.id}\\b`)).first().waitFor()
  }
  passed('real_course_materials_and_stable_document_ids_render')
  await screenshot(page, 'live-course-information')

  phase = 'generated_plan'
  await page.getByRole('link', { name: 'Plan', exact: true }).click()
  await page.getByRole('button', { name: 'Version history', exact: true }).waitFor()
  for (const chapter of initialPlan.plan.chapters) {
    await page.getByRole('heading', { name: chapter.title, exact: true }).first().waitFor()
  }
  await page.getByRole('heading', { name: 'Estimated study time', exact: true }).waitFor()
  passed('actual_generated_chapters_estimates_and_current_version_render')
  await screenshot(page, 'live-generated-plan')

  phase = 'source_pdf'
  await page.locator('.source-chip').first().click()
  const sourceDialog = page.getByRole('dialog', { name: 'Source reference', exact: true })
  const originalLink = sourceDialog.getByRole('link', { name: 'Open original PDF at this page', exact: true })
  await originalLink.waitFor()
  const originalHref = await originalLink.getAttribute('href')
  const match = originalHref.match(new RegExp(`^/api/courses/${courseId}/documents/(\\d+)/file#page=(\\d+)$`))
  assert(match, 'Reference must preserve its actual document ID and original page')
  const original = inventory.documents.find((document) => Number(document.id) === Number(match[1]))
  assert(original?.original_pdf_available && original.page_numbers.includes(Number(match[2])))
  const pdf = await page.request.get(baseUrl + originalHref.split('#')[0])
  assert.equal(pdf.status(), 200)
  const pdfBytes = await pdf.body()
  assert.equal(crypto.createHash('sha256').update(pdfBytes).digest('hex'), original.sha256)
  assert(pdfBytes.subarray(0, 5).equals(Buffer.from('%PDF-')))
  passed('visible_source_dialog_links_to_exact_authenticated_original_pdf', { document_id: original.id, original_page: Number(match[2]) })
  await sourceDialog.getByRole('button', { name: 'Close dialog', exact: true }).click()

  phase = 'read_only_versions'
  assert(initialVersions.versions.length > 0, 'A saved version is required')
  const oldest = Math.min(...initialVersions.versions.map((version) => Number(version.version)))
  await page.getByRole('button', { name: 'Version history', exact: true }).click()
  const historyDialog = page.getByRole('dialog', { name: 'Plan version history', exact: true })
  await historyDialog.getByText(/Saved schedules are read-only/).waitFor()
  await historyDialog.getByRole('button', { name: `View version ${oldest}`, exact: true }).click()
  await historyDialog.getByRole('heading', { name: `Saved plan v${oldest}`, exact: true }).waitFor()
  assert.equal(await historyDialog.getByRole('button', { name: /Reschedule|Mark complete|Start practice|Include new/ }).count(), 0)
  await historyDialog.getByRole('button', { name: 'Close dialog', exact: true }).click()
  assert.equal(fingerprint((await json(page.request, baseUrl + base + '/plan')).plan), initialPlanHash)
  passed('saved_plan_history_opens_read_only_without_replacing_current_plan')

  phase = 'real_calendar'
  const firstTask = initialPlan.plan.tasks[0]
  assert(firstTask?.date, 'A scheduled generated task is required')
  await navigate(page, `/calendar?course=${courseId}&date=${encodeURIComponent(firstTask.date)}`)
  const day = page.getByRole('complementary', { name: 'Selected day overview', exact: true })
  await day.waitFor()
  const dayTasks = initialPlan.plan.tasks.filter((task) => task.date === firstTask.date)
  assert.equal(await day.locator('.day-task').count(), dayTasks.length)
  for (const task of dayTasks) await day.getByRole('heading', { name: task.title, exact: true }).waitFor()
  passed('real_calendar_day_contains_the_saved_scheduled_tasks')

  phase = 'real_practice_index'
  await navigate(page, `/practice?course=${courseId}`)
  phase = 'real_practice_index.heading'
  await page.getByRole('heading', { name: 'Chapter practice', exact: true }).waitFor()
  phase = 'real_practice_index.filter'
  assert.equal(await page.getByLabel('Filter practice by course', { exact: true }).inputValue(), String(courseId))
  assert.equal(await page.locator('.practice-grid .practice-chapter').count(), initialPlan.plan.chapters.length)
  passed('real_practice_index_preserves_generated_chapters_without_starting_sessions')

  phase = 'saved_practice_report'
  await navigate(page, `/courses/${courseId}/chapters/${chapterId}/reports`)
  await page.getByRole('heading', { level: 1, name: initialState.chapter_title, exact: true }).waitFor()
  const sessionLink = page.locator(`a[href="/practice/${courseId}/sessions/${sessionId}"]`)
  await sessionLink.waitFor()
  await sessionLink.click()
  await page.getByText('Practice report', { exact: true }).waitFor()
  await page.getByRole('heading', { name: 'Round results', exact: true }).waitFor()
  const roundCards = page.locator('.report-rounds > div')
  assert.equal(await roundCards.count(), initialState.round_results.length)
  for (let index = 0; index < initialState.round_results.length; index += 1) {
    const round = initialState.round_results[index]
    await roundCards.nth(index).getByText(`Round ${round.round_number} of 2`, { exact: true }).waitFor()
    await roundCards.nth(index).getByText(`${round.correct_count} of ${round.total} correct`, { exact: true }).waitFor()
  }
  passed('real_report_list_opens_saved_report_with_separate_round_counts')
  await page.getByRole('button', { name: 'Wrong only', exact: true }).click()
  assert.equal(await page.locator('.practice-session article.panel').count(), initialState.report.wrong_count)
  await page.getByRole('button', { name: 'All', exact: true }).click()
  assert.equal(await page.locator('.practice-session article.panel').count(), initialState.report.question_count)
  passed('actual_report_question_filters_match_saved_grades')
  await screenshot(page, 'live-practice-report')
  await page.reload()
  await page.getByRole('heading', { name: 'Round results', exact: true }).waitFor()
  assert.equal(gradeSnapshot(await json(page.request, baseUrl + base + `/practice/${sessionId}`)), initialGrade)
  passed('refresh_reopens_same_finished_report_without_rescoring')

  phase = 'qa_history'
  const qa = await json(page.request, baseUrl + base + '/questions')
  const records = Array.isArray(qa) ? qa : qa.questions
  assert(Array.isArray(records) && records.length > 0, 'An actual integration Q&A record is required')
  await navigate(page, `/courses/${courseId}/qa`)
  await page.getByRole('heading', { name: 'Q&A history', exact: true }).waitFor()
  assert.equal(await page.locator('.qa-history-item').count(), records.length)
  await page.locator('.qa-history-item').last().click()
  assert.equal(await page.locator('.qa-history-item[aria-pressed="true"]').count(), 1)
  await page.reload()
  await page.locator('.qa-history-item').first().waitFor()
  assert.equal(await page.locator('.qa-history-item').count(), records.length)
  passed('real_qa_history_survives_refresh_without_new_question_submission')
  await screenshot(page, 'live-qa-history')

  phase = 'mobile_plan'
  await page.setViewportSize({ width: 390, height: 844 })
  await navigate(page, `/courses/${courseId}/plan`)
  await page.getByRole('button', { name: 'Version history', exact: true }).waitFor()
  const width = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth,
    main: document.querySelector('#main-content').clientWidth, mainScroll: document.querySelector('#main-content').scrollWidth }))
  assert(width.document <= width.viewport + 2 && width.mainScroll <= width.main + 2, 'Actual mobile plan should fit its viewport')
  passed('actual_mobile_plan_fits_viewport')
  await screenshot(page, 'live-plan-mobile')

  phase = 'read_only_invariants'
  assert.equal(gradeSnapshot(await json(page.request, baseUrl + base + `/practice/${sessionId}`)), initialGrade)
  assert.equal(fingerprint((await json(page.request, baseUrl + base + '/plan')).plan), initialPlanHash)
  assert.equal(fingerprint(await json(page.request, baseUrl + base + '/plan/versions')), fingerprint(initialVersions))
  assert.equal(businessMutations.length, 0, 'Read-only acceptance must not submit model or scoring requests')
  assert.equal(pageErrors.length, 0, 'No browser runtime exceptions')
  assert.equal(badResponses.length, 0, 'No authenticated application HTTP errors')
  passed('no_business_mutations_no_model_submissions_and_saved_data_unchanged')
  passed('no_browser_runtime_or_authenticated_api_errors')
  result.status = 'passed'
}

run().catch(async (error) => {
  result.status = 'failed'
  // Playwright call logs can contain typed values. Never export error messages,
  // stacks, credentials, request bodies, cookies, storage state or page HTML.
  result.failure = { phase, type: error.name || 'Error' }
  if (currentPage && !currentPage.isClosed()) {
    try {
      result.failure.view = await currentPage.evaluate(() => ({
        pathname: location.pathname,
        headings: [...document.querySelectorAll('h1,h2,h3')].filter((element) => element.getClientRects().length)
          .slice(0, 20).map((element) => element.innerText.slice(0, 160)),
        buttons: [...document.querySelectorAll('button')].filter((element) => element.getClientRects().length)
          .slice(0, 30).map((element) => (element.getAttribute('aria-label') || element.innerText).slice(0, 100)),
      }))
      await screenshot(currentPage, 'failure-' + phase.replace(/[^a-zA-Z0-9_-]/g, '_'))
    } catch (_) { result.failure.diagnostic_capture = 'unavailable' }
  }
  process.exitCode = 1
}).finally(async () => {
  if (browser) await browser.close()
  result.finished_at = new Date().toISOString()
  save()
  process.stdout.write(JSON.stringify(result, null, 2) + '\n')
})
