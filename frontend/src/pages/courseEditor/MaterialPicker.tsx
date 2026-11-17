import { useState } from 'react'
import {
  FileText,
  Upload,
  X,
} from 'lucide-react'

import './materialPicker.css'

export function fileKey(file: File) {
  return (
    `${file.name}:` +
    `${file.size}:` +
    file.lastModified
  )
}

function isPdf(file: File) {
  const name = file.name.toLowerCase()
  return name.endsWith('.pdf') && file.size > 0
}

function mergeFiles(current: File[], incoming: File[]) {
  const selected = [...current, ...incoming.filter(isPdf)]
  return selected.filter(
    (file, index) =>
      selected.findIndex(
        (item) => fileKey(item) === fileKey(file),
      ) === index,
  )
}

export default function MaterialPicker({
  files,
  onChange,
  disabled = false,
}: {
  files: File[]
  onChange: (files: File[]) => void
  disabled?: boolean
}) {
  const [dragging, setDragging] = useState(false)

  return (
    <div className="material-picker">
      <label
        className={
          dragging
            ? 'upload-zone is-dragging'
            : 'upload-zone'
        }
        onDragEnter={(event) => {
          event.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragOver={(event) => {
          event.preventDefault()
          if (!disabled) setDragging(true)
        }}
        onDragLeave={(event) => {
          event.preventDefault()
          setDragging(false)
        }}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (disabled) return
          onChange(
            mergeFiles(
              files,
              Array.from(event.dataTransfer.files || []),
            ),
          )
        }}
      >
        <Upload
          size={22}
          strokeWidth={1.4}
        />

        <strong>
          Add course materials
        </strong>

        <span>
          Choose or drop one or more PDF files
        </span>

        <input
          type="file"
          accept=".pdf,application/pdf"
          multiple
          disabled={disabled}
          onChange={(event) => {
            onChange(
              mergeFiles(
                files,
                Array.from(event.target.files || []),
              ),
            )
            event.target.value = ''
          }}
        />
      </label>

      {files.length > 0 && (
        <ul className="pending-files">
          {files.map((file) => (
            <li key={fileKey(file)}>
              <FileText size={15} />

              <span>{file.name}</span>

              <small>
                {Math.max(
                  1,
                  Math.round(file.size / 1024),
                )}{' '}
                KB
              </small>

              <button
                className="icon-button"
                type="button"
                aria-label={`Remove ${file.name}`}
                disabled={disabled}
                onClick={() =>
                  onChange(
                    files.filter(
                      (item) =>
                        fileKey(item) !== fileKey(file),
                    ),
                  )
                }
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
