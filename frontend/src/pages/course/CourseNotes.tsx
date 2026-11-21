import { useState } from 'react'
import type { FormEvent } from 'react'
import { BookOpen, Download, FileText, LayoutGrid, LoaderCircle } from 'lucide-react'

import type { CourseDetail } from './types'
import DocumentPicker, {
  usableMaterials,
} from './DocumentPicker'
import { downloadNotes } from './api'
import { messageOf } from '../../shared/request'
import { Link } from '../../shared/router'
import { Notice } from '../../shared/components/UI'

import './courseResources.css'

type NotesMode = 'notes' | 'cheatsheet'
type PaperSize = 'a4' | 'a5' | 'letter'
type SheetSides = 'single' | 'double'
type TypeSize = 'large' | 'medium' | 'small' | 'tiny'

const outputOptions = [
  { value: 'notes', title: 'Study notes', description: 'Readable explanations across multiple pages.', icon: BookOpen },
  { value: 'cheatsheet', title: 'Cheatsheet', description: 'A compact reference for quick revision.', icon: LayoutGrid },
] as const

function PageDiagram({ compact, doubleSided }: { compact: boolean; doubleSided: boolean }) {
  return (
    <div className="notes-paper-stage" aria-hidden="true">
      <div className={`notes-paper${doubleSided ? ' is-double-sided' : ''}`}>
        <div className="notes-page">
          <span className="notes-page-title" />
          <div className={`notes-page-content${compact ? ' is-compact' : ''}`}>
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function CourseNotes({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const demo = courseId === 'demo'
  const materials = usableMaterials(course.documents)
  const [selection, setSelection] = useState(() => ({
    documents: course.documents,
    ids: materials.map(item => item.id),
  }))
  const documentIds = selection.ids
  const [mode, setMode] = useState<NotesMode>('notes')
  const [paperSize, setPaperSize] = useState<PaperSize>('a4')
  const [sides, setSides] = useState<SheetSides>('single')
  const [typeSize, setTypeSize] = useState<TypeSize>('small')
  const [brief, setBrief] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const compact = mode === 'cheatsheet'
  const doubleSided = compact && sides === 'double'
  const paperLabel = compact ? { a4: 'A4', a5: 'A5', letter: 'Letter' }[paperSize] : 'A4'

  if (selection.documents !== course.documents) {
    const availableIds = materials.map(item => item.id)
    const kept = documentIds.filter(id => availableIds.includes(id))
    setSelection({ documents: course.documents, ids: kept.length ? kept : availableIds })
  }

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
    <div className="course-resources stack">
      <header className="resource-header">
        <span className="resource-icon" aria-hidden="true"><BookOpen size={25} /></span>
        <div>
          <h2>Notes &amp; cheatsheets</h2>
          <p>Turn your lecture PDFs into study notes or a compact reference sheet.</p>
        </div>
      </header>

      {demo || !materials.length ? (
        <section className="panel resource-panel">
          <div className="resource-empty">
            <span className="resource-icon" aria-hidden="true"><FileText size={24} /></span>
            <h3>{demo ? 'Create PDFs from your own courses' : 'Add lecture materials first'}</h3>
            <p>{demo
              ? 'Open one of your courses to generate notes or a cheatsheet.'
              : 'Upload a readable lecture PDF to start creating notes.'}</p>
            {!demo && (
              <Link className="button secondary small" href={`/courses/${courseId}/info`}>
                Open course information
              </Link>
            )}
          </div>
        </section>
      ) : (
        <form className="resource-grid notes-resource-grid" aria-busy={busy} onSubmit={submit} noValidate>
          <section className="panel resource-panel notes-form">
            <fieldset className="resource-fieldset" disabled={busy}>
              <legend>Output type</legend>
              <div className="notes-mode-options">
                {outputOptions.map(({ value, title, description, icon: Icon }) => (
                  <label className="resource-choice notes-mode-option" key={value}>
                    <input
                      type="radio"
                      name="notes-mode"
                      value={value}
                      checked={mode === value}
                      onChange={() => setMode(value)}
                    />
                    <Icon size={21} aria-hidden="true" />
                    <span>
                      <strong>{title}</strong>
                      <small>{description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="resource-fieldset notes-form-section" disabled={busy}>
              <legend>Lecture PDFs</legend>
              <DocumentPicker
                documents={course.documents}
                selectedIds={documentIds}
                disabled={busy}
                onChange={(ids) => {
                  setSelection({ documents: course.documents, ids })
                  setError('')
                }}
              />
            </fieldset>

            <label className="field notes-form-section">
              <span>Focus <small className="muted">(optional)</small></span>
              <textarea
                rows={3}
                maxLength={10000}
                value={brief}
                disabled={busy}
                onChange={(event) => {
                  setBrief(event.target.value)
                  setError('')
                }}
                placeholder={compact
                  ? 'Example: Use 3 columns and focus on formulas from chapters 2–4.'
                  : 'Example: Explain the midterm topics and include a worked example.'}
              />
            </label>
          </section>

          <aside className="panel resource-panel notes-output">
            <div className="resource-panel-heading"><h3>PDF layout</h3></div>
            <PageDiagram compact={compact} doubleSided={doubleSided} />

            {compact && (
              <div className="notes-layout-controls">
                <label className="field">
                  <span>Paper size</span>
                  <select
                    value={paperSize}
                    disabled={busy}
                    onChange={(event) => setPaperSize(event.target.value as PaperSize)}
                  >
                    <option value="a4">A4</option>
                    <option value="a5">A5</option>
                    <option value="letter">Letter</option>
                  </select>
                </label>
                <label className="field">
                  <span>Type size</span>
                  <select
                    value={typeSize}
                    disabled={busy}
                    onChange={(event) => setTypeSize(event.target.value as TypeSize)}
                  >
                    <option value="large">Large</option>
                    <option value="medium">Medium</option>
                    <option value="small">Small</option>
                    <option value="tiny">Tiny</option>
                  </select>
                </label>
                <fieldset className="resource-fieldset notes-sides" disabled={busy}>
                  <legend>Pages</legend>
                  <div className="notes-side-options">
                    <label className="resource-choice">
                      <input type="radio" name="sheet-sides" checked={!doubleSided} onChange={() => setSides('single')} />
                      <span>1 page</span>
                    </label>
                    <label className="resource-choice">
                      <input type="radio" name="sheet-sides" checked={doubleSided} onChange={() => setSides('double')} />
                      <span>2 pages</span>
                    </label>
                  </div>
                </fieldset>
              </div>
            )}

            <dl className="notes-output-summary" aria-live="polite">
              <div>
                <dt>Format</dt>
                <dd>{paperLabel} · {compact ? doubleSided ? '2 pages' : '1 page' : 'Multiple pages'}</dd>
              </div>
              <div>
                <dt>Selected</dt>
                <dd>{documentIds.length} {documentIds.length === 1 ? 'lecture PDF' : 'lecture PDFs'}</dd>
              </div>
            </dl>

            <div className="resource-form-footer notes-output-footer">
              <button type="submit" className="button" disabled={busy || !documentIds.length}>
                {busy ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <Download size={16} aria-hidden="true" />}
                {busy ? 'Generating PDF…' : compact ? 'Generate cheatsheet PDF' : 'Generate study notes PDF'}
              </button>
            </div>
            {error && <Notice tone="error">{error}</Notice>}
            {message && <Notice tone={busy ? 'info' : 'success'}>{message}</Notice>}
          </aside>
        </form>
      )}
    </div>
  )
}
