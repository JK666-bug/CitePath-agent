const assert = require('node:assert/strict')
const { serveBuilt } = require('./serve-built.cjs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseUrl = process.env.CITEPATH_UI_URL || (process.env.CITEPATH_UI_DIST ? 'http://citepath.test' : 'http://127.0.0.1:5174')

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  page.setDefaultTimeout(10000)
  await serveBuilt(page, process.env.CITEPATH_UI_DIST, baseUrl)
  const source = { document_id: 42, position: 1, filename: 'hashing.pdf', page_number: 7 }
  const addedSource = { document_id: 67, position: 2, filename: 'trees.pdf', page_number: 2 }
  const profile = { goal: 'Understand hashing', prior_knowledge: 'Basic algorithms', daily_minutes: 20, reading_words_per_minute: 180 }
  const materialUpdate = { new_page_count: 2, new_document_ids: [67], missing_document_ids: [], can_update: true }
  const noNewMaterial = { new_page_count: 0, new_document_ids: [], missing_document_ids: [], can_update: false }
  let plan = {
    version: 1, start: '2026-11-12', end: '2026-11-13', reason: 'Original schedule',
    planning_profile: profile, estimated_total_minutes: 55,
    estimate_basis: 'Reading estimates use the selected pace; practice and review include a study allowance.',
    capacity: { available_minutes: 40, remaining_estimated_minutes: 45, over_capacity: true },
    chapters: [{ id: '10', title: 'Hashing', concepts: ['Hash functions'], sources: [source], estimated_minutes: 55 }],
    tasks: [
      { id: 'read-10', chapterId: '10', title: 'Read the introduction', kind: 'Reading', date: '2026-11-12', status: 'Completed', sources: [source], concepts: ['Hash functions'], estimated_minutes: 10 },
      { id: 'read-11', chapterId: '10', title: 'Read the worked example', kind: 'Reading', date: '2026-11-12', status: 'Not started', sources: [source], concepts: ['Hash functions'], estimated_minutes: 15 },
      { id: 'practice-10', chapterId: '10', title: 'Practice hashing', kind: 'Practice', date: '2026-11-12', status: 'Not started', sources: [source], concepts: ['Hash functions'], estimated_minutes: 20 },
      { id: 'review-10', chapterId: '10', title: 'Review hashing', kind: 'Review', date: '2026-11-12', status: 'Not started', sources: [source], concepts: ['Hash functions'], estimated_minutes: 10 },
    ],
  }
  let snapshot
  let newPlan = null
  let failHistory = true
  let failSnapshot = true
  const calls = []
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const questions = [
    { id: 'goal', prompt: 'What would you like to learn?', required: true },
    { id: 'prior_knowledge', prompt: 'What do you know already?', required: true },
    { id: 'daily_minutes', prompt: 'How many minutes can you study each day?', required: true },
  ]
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postData() ? JSON.parse(request.postData()) : null
    calls.push({ method: request.method(), path, body })
    let result
    if (path === '/api/me') result = { id: 1, username: 'Tester' }
    else if (path === '/api/courses') result = { courses: [1, 2].map((id) => ({ id, name: id === 1 ? 'Algorithms' : 'New course', student_brief: 'Keep my study preferences', created_at: '2026-11-12', document_count: 2 })) }
    else if (/^\/api\/courses\/[12]$/.test(path)) result = { id: Number(path.split('/').at(-1)), name: path.endsWith('/1') ? 'Algorithms' : 'New course', student_brief: 'Keep my study preferences', created_at: '2026-11-12', documents: [{ id: 42, position: 1, filename: 'hashing.pdf', ingest_status: 'complete', usable_page_count: 10, page_count: 10 }, { id: 67, position: 2, filename: 'trees.pdf', ingest_status: 'complete', usable_page_count: 2, page_count: 2 }] }
    else if (path === '/api/courses/1/plan/versions') {
      if (failHistory) {
        failHistory = false
        return route.fulfill({ status: 503, json: { detail: 'Saved schedules are temporarily unavailable. Try again.' } })
      }
      result = { read_only: true, versions: [{ version: 1, reason: 'Original schedule', created_at: '2026-11-12 09:00', change_type: 'materials_updated' }] }
    } else if (path === '/api/courses/1/plan/versions/1') {
      if (failSnapshot) {
        failSnapshot = false
        return route.fulfill({ status: 503, json: { detail: 'Could not load this saved schedule. Try again.' } })
      }
      result = { version: 1, plan: snapshot, saved_at: '2026-11-12 09:00', change_type: 'materials_updated', read_only: true }
    } else if (path === '/api/courses/1/plan/tasks/read-11/complete') {
      plan.tasks.find((task) => task.id === 'read-11').status = 'Completed'
      plan.capacity = { available_minutes: 40, remaining_estimated_minutes: 30, over_capacity: false }
      // Older completion responses may omit planning metadata; the cached update notice must survive.
      result = { status: 'ready', plan }
    } else if (path === '/api/courses/1/plan') {
      if (request.method() === 'POST') {
        assert.equal(body.expected_version, plan.version)
        if (!body.profile.goal || !body.profile.prior_knowledge || !body.profile.daily_minutes) {
          result = { status: 'needs_input', questions, profile: body.profile, plan, material_update: materialUpdate }
        } else if (body.update_materials && plan.version === 1) {
          snapshot = structuredClone(plan)
          plan = { ...plan, version: 2, reason: 'Added new lecture material', planning_profile: body.profile, estimated_total_minutes: 80,
            capacity: { available_minutes: 40, remaining_estimated_minutes: 55, over_capacity: true },
            chapters: [...plan.chapters, { id: '20', title: 'Trees', concepts: ['Tree traversal'], sources: [addedSource], estimated_minutes: 25 }],
            tasks: [...plan.tasks, { id: 'read-20', chapterId: '20', title: 'Read tree traversal', kind: 'Reading', date: '2026-11-12', status: 'Not started', sources: [addedSource], concepts: ['Tree traversal'], estimated_minutes: 25 }],
          }
          result = { status: 'ready', plan, material_update: noNewMaterial }
        } else return route.fulfill({ status: 409, json: { detail: 'The saved plan changed. Reload it before updating.' } })
      } else result = { status: 'ready', plan, material_update: plan.version === 1 ? materialUpdate : noNewMaterial }
    } else if (path === '/api/courses/2/plan') {
      if (request.method() === 'POST') {
        assert.equal(body.expected_version, undefined)
        if (!body.profile.goal || !body.profile.prior_knowledge || !body.profile.daily_minutes) result = { status: 'needs_input', questions, profile: body.profile, plan: null }
        else {
          newPlan = { ...plan, version: 1, planning_profile: body.profile, reason: 'New personalized schedule' }
          result = { status: 'ready', plan: newPlan, material_update: noNewMaterial }
        }
      } else result = { status: newPlan ? 'ready' : 'empty', plan: newPlan }
    } else return route.fulfill({ status: 404, json: { detail: `Unhandled mock ${path}` } })
    await route.fulfill({ json: result })
  })
  try {
    await page.goto(baseUrl + '/courses/1/plan')
    await page.getByRole('heading', { name: 'Estimated study time', exact: true }).waitFor()
    const estimates = page.locator('.plan-estimates')
    await estimates.getByText('55 min', { exact: true }).waitFor()
    await estimates.getByText('45 min', { exact: true }).waitFor()
    await estimates.getByText('Over your daily budget', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Read the worked example', exact: true }).locator('..').locator('..').getByRole('button', { name: 'Mark complete', exact: true }).click()
    await estimates.getByText('30 min', { exact: true }).waitFor()
    await page.getByLabel('Include new materials when updating this plan', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('Learning goal', { exact: true }).inputValue(), profile.goal)

    await page.getByLabel('Learning goal', { exact: true }).fill('')
    await page.getByLabel('Prior knowledge', { exact: true }).fill('')
    await page.getByLabel('Available study minutes per day', { exact: true }).fill('')
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).click()
    await page.getByText('A few details will make this plan useful.', { exact: true }).waitFor()
    await page.getByText('What would you like to learn?', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('Learning goal', { exact: true }).getAttribute('aria-invalid'), 'true')
    assert.equal(await page.locator('.plan-version').textContent().then((text) => text.includes('Plan v1')), true)
    assert.equal(await page.locator('.plan-task.completed').count(), 2)
    assert.equal(await page.getByLabel('Study brief and preferences', { exact: true }).inputValue(), 'Keep my study preferences')

    await page.getByLabel('Learning goal', { exact: true }).fill('Apply hashing and trees')
    await page.getByLabel('Prior knowledge', { exact: true }).fill('Basic algorithms; new to trees')
    await page.getByLabel('Available study minutes per day', { exact: true }).fill('20')
    await page.getByLabel('Estimated reading pace (words per minute)', { exact: true }).fill('150')
    await page.getByLabel('Include new materials when updating this plan', { exact: true }).check()
    await page.getByRole('button', { name: 'Include new materials and update plan', exact: true }).click()
    await page.getByRole('heading', { name: 'Trees', exact: true }).waitFor()
    await estimates.getByText('80 min', { exact: true }).waitFor()
    assert.equal(await page.getByLabel('Study brief and preferences', { exact: true }).inputValue(), 'Keep my study preferences')
    assert.equal(await page.locator('.plan-task.completed').count(), 2)
    assert.equal(await page.getByRole('link', { name: 'View reports', exact: true }).getAttribute('href'), '/courses/1/chapters/10/reports')
    assert.equal(await page.getByLabel('Include new materials when updating this plan', { exact: true }).count(), 0)
    const updateCall = calls.filter((call) => call.path === '/api/courses/1/plan' && call.method === 'POST').at(-1)
    assert.equal(updateCall.body.expected_version, 1)
    assert.equal(updateCall.body.update_materials, true)
    assert.equal(updateCall.body.profile.reading_words_per_minute, 150)
    if (process.env.CITEPATH_SCREENSHOT) await page.screenshot({ path: process.env.CITEPATH_SCREENSHOT, fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'planner should fit a mobile viewport')
    if (process.env.CITEPATH_SCREENSHOT) await page.screenshot({ path: process.env.CITEPATH_SCREENSHOT.replace(/\.png$/, '-mobile.png'), fullPage: true })
    await page.setViewportSize({ width: 1280, height: 1000 })

    await page.getByRole('button', { name: 'Version history', exact: true }).click()
    const history = page.getByRole('dialog', { name: 'Plan version history', exact: true })
    await history.getByRole('alert').waitFor()
    assert.equal(await history.getByText('No earlier plan snapshots have been saved yet.', { exact: true }).count(), 0)
    await history.getByRole('button', { name: 'Retry version history', exact: true }).click()
    await history.getByRole('button', { name: 'View version 1', exact: true }).click()
    await history.getByRole('alert').waitFor()
    await history.getByRole('button', { name: 'View version 1', exact: true }).click()
    await history.getByRole('heading', { name: 'Saved plan v1', exact: true }).waitFor()
    assert.equal(await history.getByRole('heading', { name: 'Trees', exact: true }).count(), 0)
    assert.equal(await history.getByRole('button', { name: /Mark complete|Reschedule|Restore/ }).count(), 0)
    await history.getByRole('button', { name: 'Doc 42 · p. 7', exact: true }).click()
    const sourceDialog = page.getByRole('dialog', { name: 'Source reference', exact: true })
    await sourceDialog.getByText('Document 42 · Original PDF page 7', { exact: true }).waitFor()
    assert.equal(await sourceDialog.getByRole('link', { name: 'Open original PDF at this page' }).getAttribute('href'), '/api/courses/1/documents/42/file#page=7')
    await sourceDialog.getByRole('button', { name: 'Close dialog', exact: true }).click()
    await history.getByRole('button', { name: 'Close dialog', exact: true }).click()
    assert.equal(calls.filter((call) => call.path.includes('/plan/versions')).every((call) => call.method === 'GET'), true)

    await page.getByLabel('Learning goal', { exact: true }).fill('Keep this unsaved goal after a conflict')
    await page.getByRole('button', { name: 'Reschedule plan', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'Your study plan or materials changed.' }).waitFor()
    assert.equal(await page.getByLabel('Learning goal', { exact: true }).inputValue(), 'Keep this unsaved goal after a conflict')
    assert.equal(await page.locator('.plan-version').textContent().then((text) => text.includes('Plan v2')), true)
    await page.getByRole('button', { name: 'Reload saved plan', exact: true }).click()
    await page.getByRole('alert').waitFor({ state: 'hidden' })

    await page.goto(baseUrl + '/courses/2/plan')
    await page.getByRole('button', { name: 'Generate plan', exact: true }).click()
    await page.getByText('A few details will make this plan useful.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('heading', { name: 'Your course progress', exact: true }).count(), 0)
    await page.getByLabel('Learning goal', { exact: true }).fill('Study the core ideas')
    await page.getByLabel('Prior knowledge', { exact: true }).fill('Beginner')
    await page.getByLabel('Available study minutes per day', { exact: true }).fill('45')
    await page.getByRole('button', { name: 'Generate plan', exact: true }).click()
    await page.getByRole('heading', { name: 'Your course progress', exact: true }).waitFor()
    assert.equal(newPlan.planning_profile.daily_minutes, 45)
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ result: 'PASS', checks: ['estimates and daily budget', 'task completion retains new-material metadata', 'clarification preserves existing work and preferences', 'explicit append sends saved version and profile', 'completed tasks and report links survive updates', 'legacy preferences round trip without a deadline', 'mobile viewport fits', 'read-only historical version and stable document links', 'history failures retry without false empty state', 'conflict preserves entered profile and current plan', 'reload saved plan after conflict', 'new plan waits for clarification'], requests: calls.length }, null, 2))
  } finally {
    await browser.close()
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1 })
