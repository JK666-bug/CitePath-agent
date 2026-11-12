const assert = require('node:assert/strict')
const { serveBuilt } = require('./serve-built.cjs')
const { inventoryOf } = require('./mock-inventory.cjs')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseUrl = 'http://citepath.test'

async function run() {
  const browser = await chromium.launch({ headless: true, channel: process.env.CITEPATH_BROWSER || 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
    page.setDefaultTimeout(10000)
    await serveBuilt(page, process.env.CITEPATH_UI_DIST || 'dist', baseUrl)
    const source = { document_id: 42, filename: 'hashing.pdf', page_number: 7 }
    const other = { document_id: 67, filename: 'trees.pdf', page_number: 2 }
    let inventory = inventoryOf([source, other])
    inventory.documents[0].active = false
    inventory.documents[0].position = null
    inventory.documents[0].removed_at = '2026-11-12'
    let missingFile = false, failRestore = true
    const mutations = [], errors = []
    page.on('pageerror', error => errors.push(error.message))
    const plan = { version: 3, start: '2026-11-12', end: '2026-12-01', reason: 'Preserved plan', tasks: [],
      chapters: [{ id: '10', title: 'Hashing', concepts: ['Hashing'], sources: [source, { document_id: 404, filename: 'old.pdf', page_number: 3 }] }] }
    await page.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (request.method() !== 'GET') mutations.push(path)
      let result
      const course = { id: 1, name: 'Algorithms', student_brief: 'Study algorithms', created_at: '2026-11-12',
        documents: inventory.documents.filter(row => row.active).map(row => ({ ...row, ingest_status: 'complete' })) }
      if (path === '/api/me') result = { id: 1, username: 'Tester' }
      else if (path === '/api/courses') result = { courses: [{ ...course, document_count: course.documents.length }] }
      else if (path === '/api/courses/1') result = course
      else if (path.endsWith('/documents/inventory')) result = { documents: inventory.documents.map(row => ({ ...row, original_pdf_available: row.id === 42 ? !missingFile : true })) }
      else if (path === '/api/courses/1/plan') result = { status: 'ready', plan,
        material_update: { missing_document_ids: [42, 404], new_document_ids: [], new_page_count: 0, can_update: false } }
      else if (path.endsWith('/documents/42/restore')) {
        if (failRestore) {
          failRestore = false
          return route.fulfill({ status: 502, json: { detail: 'Vector indexing failed; restore again.' } })
        }
        inventory.documents[0].active = true
        inventory.documents[0].position = 2
        result = { document_id: 42, restored: true, ingest_status: 'complete' }
      } else if (path.endsWith('/documents/42') && request.method() === 'DELETE') {
        inventory.documents[0].active = false
        inventory.documents[0].position = null
        result = { ok: true, document_id: 42, archived: true }
      } else return route.fulfill({ status: 404, json: { detail: 'Unhandled mock' } })
      await route.fulfill({ json: result })
    })
    await page.goto(baseUrl + '/courses/1/plan')
    await page.getByRole('button', { name: 'Doc 42 · p. 7', exact: true }).click()
    await page.getByText('Archived material.', { exact: false }).waitFor()
    assert.equal(await page.getByRole('link', { name: 'Open original PDF at this page' }).getAttribute('href'), '/api/courses/1/documents/42/file#page=7')
    await page.getByRole('button', { name: 'Close dialog' }).click()
    await page.getByRole('button', { name: 'Doc 404 · p. 3', exact: true }).click()
    await page.getByText('Original source unavailable.', { exact: false }).waitFor()
    assert.equal(await page.getByRole('link', { name: 'Open original PDF at this page' }).count(), 0)
    await page.getByRole('button', { name: 'Close dialog' }).click()
    missingFile = true
    await page.getByRole('button', { name: 'Doc 42 · p. 7', exact: true }).click()
    await page.getByText('Original PDF or page unavailable.', { exact: false }).waitFor()
    assert.equal(await page.getByRole('link', { name: 'Open original PDF at this page' }).count(), 0)
    await page.getByRole('button', { name: 'Close dialog' }).click()
    missingFile = false
    await page.goto(baseUrl + '/courses/1/info')
    await page.getByRole('heading', { name: 'Archived materials', exact: true }).waitFor()
    await page.getByRole('button', { name: 'Restore material', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'Restoration did not finish' }).waitFor()
    assert.equal(inventory.documents[0].active, false)
    await page.getByRole('button', { name: 'Restore material', exact: true }).click()
    await page.getByRole('heading', { name: 'Archived materials', exact: true }).waitFor({ state: 'hidden' })
    assert.equal(inventory.documents[0].id, 42)
    const materialRow = page.getByRole('listitem').filter({ hasText: 'hashing.pdf' })
    await materialRow.getByRole('button', { name: 'Remove from course', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Remove material from course?', exact: true })
    await dialog.getByText('The original PDF, source ID and learning history stay saved and can be restored.', { exact: false }).waitFor()
    await dialog.getByRole('button', { name: 'Remove from course', exact: true }).click()
    await page.getByRole('heading', { name: 'Archived materials', exact: true }).waitFor()
    assert.equal(inventory.documents[0].id, 42)
    assert.equal(plan.version, 3)
    assert.deepEqual(errors, [])
    assert.equal(mutations.filter(path => /practice|exams|questions|\/plan/.test(path)).length, 0)
    console.log(JSON.stringify({ result: 'PASS', mode: 'mocked_api_browser', checks: [
      'archived source retains original PDF ID and page', 'physically missing IDs show no replacement link',
      'missing original file has actionable recovery guidance', 'failed vector restore stays archived and retryable',
      'successful restore keeps stable document identity', 'removal explains retained history and archives material',
      'source lookup and restoration never rescore or regenerate practice', 'no browser errors'
    ] }, null, 2))
  } finally { await browser.close() }
}
run().catch(error => { console.error(error); process.exitCode = 1 })
