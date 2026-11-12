function inventoryOf(sources) {
  const rows = new Map()
  for (const source of sources) {
    const row = rows.get(source.document_id) || { id: source.document_id, filename: source.filename,
      active: true, removed_at: null, original_pdf_available: true, page_numbers: [],
      position: source.position || 1, sha256: 'a'.repeat(64), ingest_status: 'complete', ingest_error: null }
    row.page_numbers.push(source.page_number)
    row.page_numbers = [...new Set(row.page_numbers)]
    row.page_count = Math.max(...row.page_numbers)
    row.usable_page_count = row.page_numbers.length
    rows.set(source.document_id, row)
  }
  return { documents: [...rows.values()] }
}
module.exports = { inventoryOf }
