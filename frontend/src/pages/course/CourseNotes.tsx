import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import type { CourseDetail } from './types'
import DocumentPicker, {
  usableMaterials,
} from './DocumentPicker'
import { downloadNotes } from './api'
import { messageOf } from '../../shared/request'
import { Link } from '../../shared/router'
import { Notice } from '../../shared/components/UI'

type NotesMode = 'notes' | 'cheatsheet'
type PaperSize = 'a4' | 'a5' | 'letter'
type SheetSides = 'single' | 'double'
type TypeSize = 'large' | 'medium' | 'small' | 'tiny'

export default function CourseNotes({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const demo = courseId === 'demo'
  const materials = usableMaterials(course.documents)
  const [documentIds, setDocumentIds] = useState(
    () => materials.map((item) => item.id),
  )
  const [mode, setMode] = useState<NotesMode>('notes')
  const [paperSize, setPaperSize] = useState<PaperSize>('a4')
  const [sides, setSides] = useState<SheetSides>('single')
  const [typeSize, setTypeSize] = useState<TypeSize>('small')
  const [brief, setBrief] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    const ready = new Set(materials.map((item) => item.id))
    setDocumentIds((current) => {
      const kept = current.filter((id) => ready.has(id))
      return kept.length ? kept : materials.map((item) => item.id)
    })
  }, [course.documents])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || demo) return
    if (!documentIds.length) {
      setError('Select at least one lecture PDF.')
      return
    }
    setBusy(true)
    setError('')
    setMessage(
      mode === 'cheatsheet'
        ? `Writing a ${sides === 'double' ? '2-page' : '1-page'} ${paperSize.toUpperCase()} cheatsheet…`
        : 'Writing study notes from the selected lectures…',
    )
    try {
      await downloadNotes(
        Number(courseId),
        brief,
        documentIds,
        mode,
        mode === 'cheatsheet' ? paperSize : 'a4',
        mode === 'cheatsheet' ? sides : 'single',
        mode === 'cheatsheet' ? typeSize : 'medium',
      )
      setMessage(
        mode === 'cheatsheet'
          ? 'Cheatsheet PDF downloaded.'
          : 'Study notes PDF downloaded.',
      )
    } catch (reason) {
      setMessage('')
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <section className="panel">
        <h2>Notes &amp; cheatsheets</h2>
        <p className="muted">
          Default: reformat the selected lectures with similar coverage.
          Cheatsheets pack the page and can use 1–3 columns from your brief.
          Adjust type size for denser sheets, plus single-sided (1 page) or
          double-sided (2 pages).
        </p>
      </section>

      {demo ? (
        <Notice>
          Notes generation is available in real courses only.
        </Notice>
      ) : !materials.length ? (
        <Notice>
          Upload a readable lecture PDF on{' '}
          <Link href={`/courses/${courseId}/info`}>Course information</Link>{' '}
          first.
        </Notice>
      ) : (
        <form className="panel stack" onSubmit={submit} noValidate>
          <fieldset className="stack">
            <legend>Output type</legend>
            <label className="practice-prefs-check">
              <input
                type="radio"
                name="notes-mode"
                checked={mode === 'notes'}
                disabled={busy}
                onChange={() => setMode('notes')}
              />
              <span>Study notes — clearer explanations, multiple pages OK</span>
            </label>
            <label className="practice-prefs-check">
              <input
                type="radio"
                name="notes-mode"
                checked={mode === 'cheatsheet'}
                disabled={busy}
                onChange={() => setMode('cheatsheet')}
              />
              <span>Cheatsheet — dense packed sheet, adaptive columns/type</span>
            </label>
          </fieldset>

          {mode === 'cheatsheet' && (
            <>
              <label className="field">
                <span>Paper size</span>
                <select
                  className="cp-select"
                  value={paperSize}
                  disabled={busy}
                  onChange={(event) =>
                    setPaperSize(event.target.value as PaperSize)
                  }
                >
                  <option value="a4">A4</option>
                  <option value="a5">A5</option>
                  <option value="letter">Letter</option>
                </select>
              </label>
              <fieldset className="stack">
                <legend>Sides</legend>
                <label className="practice-prefs-check">
                  <input
                    type="radio"
                    name="sheet-sides"
                    checked={sides === 'single'}
                    disabled={busy}
                    onChange={() => setSides('single')}
                  />
                  <span>Single-sided — 1 page</span>
                </label>
                <label className="practice-prefs-check">
                  <input
                    type="radio"
                    name="sheet-sides"
                    checked={sides === 'double'}
                    disabled={busy}
                    onChange={() => setSides('double')}
                  />
                  <span>Double-sided — 2 pages</span>
                </label>
              </fieldset>
              <label className="field">
                <span>Type size</span>
                <select
                  className="cp-select"
                  value={typeSize}
                  disabled={busy}
                  onChange={(event) =>
                    setTypeSize(event.target.value as TypeSize)
                  }
                >
                  <option value="large">Large — more readable</option>
                  <option value="medium">Medium — balanced</option>
                  <option value="small">Small — denser</option>
                  <option value="tiny">Tiny — maximum density</option>
                </select>
              </label>
            </>
          )}

          <div className="field">
            <span>Lecture PDFs</span>
            <DocumentPicker
              documents={course.documents}
              selectedIds={documentIds}
              disabled={busy}
              onChange={(ids) => {
                setDocumentIds(ids)
                setError('')
              }}
            />
          </div>

          <label className="field">
            <span>
              {mode === 'cheatsheet'
                ? 'What should the cheatsheet emphasize?'
                : 'What should the study notes emphasize?'}
            </span>
            <textarea
              rows={4}
              maxLength={10000}
              value={brief}
              disabled={busy}
              onChange={(event) => {
                setBrief(event.target.value)
                setError('')
              }}
              placeholder={
                mode === 'cheatsheet'
                  ? 'Optional: e.g. 3 columns, denser packing / only formulas / fill the page with chapter 2–4'
                  : 'Optional: leave blank to summarize; or e.g. very detailed explanations with examples / shorter overview / focus on midterm topics'
              }
            />
          </label>

          {error && <Notice tone="error">{error}</Notice>}
          {message && <Notice>{message}</Notice>}

          <div className="actions">
            <button
              className="button"
              disabled={busy || !documentIds.length}
            >
              {busy
                ? 'Generating…'
                : mode === 'cheatsheet'
                  ? 'Generate cheatsheet PDF'
                  : 'Generate study notes PDF'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
