import type { Material } from './types'

export function usableMaterials(documents: Material[]) {
  return documents.filter(
    (document) =>
      document.ingest_status === 'complete' &&
      document.usable_page_count > 0,
  )
}

export default function DocumentPicker({
  documents,
  selectedIds,
  disabled = false,
  onChange,
}: {
  documents: Material[]
  selectedIds: number[]
  disabled?: boolean
  onChange: (ids: number[]) => void
}) {
  const ready = usableMaterials(documents)
  const selected = new Set(selectedIds)

  if (!ready.length) {
    return (
      <p className="muted small">
        No readable PDFs are ready in this course yet.
      </p>
    )
  }

  return (
    <div className="document-picker">
      <div className="document-picker-actions">
        <button
          type="button"
          className="button small secondary"
          disabled={disabled}
          onClick={() =>
            onChange(ready.map((document) => document.id))
          }
        >
          Select all
        </button>
        <button
          type="button"
          className="button small secondary"
          disabled={disabled}
          onClick={() => onChange([])}
        >
          Clear
        </button>
      </div>

      <ul className="document-picker-list">
        {ready.map((document) => {
          const checked = selected.has(document.id)
          return (
            <li key={document.id}>
              <label>
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => {
                    if (checked) {
                      onChange(
                        selectedIds.filter(
                          (id) => id !== document.id,
                        ),
                      )
                      return
                    }
                    onChange([...selectedIds, document.id])
                  }}
                />
                <span>
                  <strong>{document.filename}</strong>
                  <small>
                    Doc {document.position}
                    {' · '}
                    {document.usable_page_count} usable pages
                  </small>
                </span>
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
