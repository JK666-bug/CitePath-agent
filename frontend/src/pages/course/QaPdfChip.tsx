import { useEffect, useRef, useState } from 'react'
import { FileText } from 'lucide-react'

import type { Material } from './types'
import { usableMaterials } from './DocumentPicker'

export default function QaPdfChip({
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
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = new Set(selectedIds)
  const selectedDocs = ready.filter((item) => selected.has(item.id))

  useEffect(() => {
    if (!open) return
    function onPointer(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!ready.length) {
    return (
      <span className="qa-pdf-chip is-empty" title="No readable PDFs">
        <FileText size={14} strokeWidth={1.8} />
        <span>No PDFs</span>
      </span>
    )
  }

  const label =
    selectedDocs.length === 0
      ? 'PDFs'
      : selectedDocs.length === 1
        ? selectedDocs[0].filename
        : `${selectedDocs.length} PDFs`

  return (
    <div className="qa-pdf-chip-wrap" ref={rootRef}>
      <button
        type="button"
        className={`qa-pdf-chip${open ? ' is-open' : ''}${
          selectedDocs.length ? '' : ' is-empty'
        }`}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Choose PDFs for this answer"
        onClick={() => setOpen((value) => !value)}
      >
        <FileText size={14} strokeWidth={1.8} />
        <span className="qa-pdf-chip-label">{label}</span>
      </button>

      {open && (
        <div className="qa-pdf-popover" role="dialog" aria-label="PDF selection">
          <div className="qa-pdf-popover-actions">
            <button
              type="button"
              className="text-button"
              disabled={disabled}
              onClick={() =>
                onChange(ready.map((document) => document.id))
              }
            >
              All
            </button>
            <button
              type="button"
              className="text-button"
              disabled={disabled}
              onClick={() => onChange([])}
            >
              Clear
            </button>
          </div>
          <ul className="qa-pdf-popover-list">
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
                            selectedIds.filter((id) => id !== document.id),
                          )
                          return
                        }
                        onChange([...selectedIds, document.id])
                      }}
                    />
                    <span>{document.filename}</span>
                  </label>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
