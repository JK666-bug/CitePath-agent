import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ClipboardList, FileText, Upload } from 'lucide-react'

import {
  deleteExamCase,
  duplicateMessage,
  listExamCases,
  uploadExamCase,
  type ExamCase,
  type ExamCaseAnswerMode,
} from './api'

import { messageOf } from '../../shared/request'
import {
  Loading,
  Modal,
  Notice,
} from '../../shared/components/UI'

import './courseResources.css'

const answerOptions = [
  ['none', 'No answers'],
  ['in_case', 'In the case PDF'],
  ['file', 'Separate answer PDF'],
] as const

function CasePdfInput({
  label,
  file,
  disabled,
  onChange,
}: {
  label: string
  file: File | null
  disabled: boolean
  onChange: (file: File) => void
}) {
  return (
    <label className="case-pdf-input">
      <input
        aria-label={label}
        type="file"
        accept="application/pdf,.pdf"
        disabled={disabled}
        onChange={(event) => {
          const selected = event.currentTarget.files?.[0]
          if (selected) onChange(selected)
          event.currentTarget.value = ''
        }}
      />
      <span className="resource-icon" aria-hidden="true">
        {file ? <FileText size={18} /> : <Upload size={18} />}
      </span>
      <span className="case-pdf-copy">
        <strong>{file?.name ?? label}</strong>
        <small>{file ? 'Choose a different PDF' : 'Select a PDF file'}</small>
      </span>
    </label>
  )
}

function caseStatus(item: ExamCase) {
  if (item.ingest_status === 'pending') return { label: 'Processing', tone: 'pending' }
  if (item.ingest_status === 'complete' && item.usable_page_count > 0) {
    return { label: 'Ready', tone: 'ready' }
  }
  return {
    label: item.ingest_status === 'complete' ? 'No readable pages' : 'Unavailable',
    tone: 'error',
  }
}

export default function CourseExamCases({
  courseId,
}: {
  courseId: string
  course?: unknown
}) {
  const demo = courseId === 'demo'
  const numericId = Number(courseId)

  const [library, setLibrary] = useState<{ courseId: string; cases: ExamCase[]; error?: string } | null>(null)
  const currentLibrary = library?.courseId === courseId ? library : null
  const cases = currentLibrary?.cases ?? []
  const listError = currentLibrary?.error
  const loading = !demo && !currentLibrary
  const [operation, setOperation] = useState<'upload' | 'delete' | null>(null)
  const busy = operation !== null
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [answerFile, setAnswerFile] = useState<File | null>(null)
  const [answerMode, setAnswerMode] =
    useState<ExamCaseAnswerMode>('none')
  const [remove, setRemove] = useState<ExamCase | null>(null)

  const reload = useCallback((signal?: AbortSignal) => (
    listExamCases(Number(courseId))
      .then(({ cases }) => {
        if (!signal?.aborted) setLibrary({ courseId, cases })
      })
      .catch((reason) => {
        if (!signal?.aborted) {
          setLibrary(current => ({
            courseId,
            cases: current?.courseId === courseId ? current.cases : [],
            error: messageOf(reason),
          }))
        }
      })
  ), [courseId])

  useEffect(() => {
    if (demo) return
    const controller = new AbortController()
    void reload(controller.signal)
    return () => controller.abort()
  }, [demo, reload])

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || demo) return
    setError('')
    setMessage('')
    if (
      !file ||
      !file.name.toLowerCase().endsWith('.pdf') ||
      !file.size
    ) {
      setError('Choose a non-empty exam-case PDF.')
      return
    }
    if (answerMode === 'file') {
      if (
        !answerFile ||
        !answerFile.name.toLowerCase().endsWith('.pdf') ||
        !answerFile.size
      ) {
        setError('Choose a non-empty answer PDF for this case.')
        return
      }
    }
    setOperation('upload')
    try {
      setMessage(`Uploading and processing ${file.name}…`)
      const result = await uploadExamCase(
        numericId,
        file,
        answerMode,
        answerMode === 'file' ? answerFile : null,
      )
      if (result.duplicate) {
        setMessage(
          duplicateMessage(file.name, result.filename),
        )
      } else {
        setMessage(
          'Exam case saved. It can guide practice and exams when you choose that option.',
        )
      }
      setFile(null)
      setAnswerFile(null)
      setAnswerMode('none')
      await reload()
    } catch (reason) {
      setMessage('')
      setError(messageOf(reason))
    } finally {
      setOperation(null)
    }
  }

  async function confirmDelete() {
    if (!remove || busy || demo) return
    setOperation('delete')
    setError('')
    setMessage('')
    try {
      await deleteExamCase(numericId, remove.id)
      await reload()
      setMessage('Exam case removed.')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setOperation(null)
      setRemove(null)
    }
  }

  function answerLabel(item: ExamCase) {
    if (item.answer_mode === 'in_case') {
      return 'Answers in case'
    }
    if (item.answer_mode === 'file') {
      return item.answer_file
        ? `Answer file: ${item.answer_file.filename}`
        : 'Answer PDF unavailable'
    }
    return 'No answers'
  }

  return (
    <div className="course-resources stack">
      <header className="resource-header">
        <span className="resource-icon" aria-hidden="true"><ClipboardList size={25} /></span>
        <div>
          <h2>Exam cases</h2>
          <p>Use sample exam PDFs to guide the style of practice questions and exams.</p>
        </div>
      </header>

      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone={busy ? 'info' : 'success'}>{message}</Notice>}

      <div className={`resource-grid${demo ? ' resource-grid-single' : ''}`}>
        <section className="panel resource-panel">
          <div className="resource-panel-heading">
            <h3>Uploaded cases</h3>
            {cases.length > 0 && <span className="resource-count">{cases.length} {cases.length === 1 ? 'PDF' : 'PDFs'}</span>}
          </div>

          {listError && !loading && (
            <Notice tone="error">
              {listError}{' '}
              <button type="button" className="text-button" onClick={() => {
                if (!cases.length) setLibrary(null)
                void reload()
              }}>Try again</button>
            </Notice>
          )}

          {cases.length > 0 ? (
            <ul className="exam-case-list">
              {cases.map((item) => {
                const status = caseStatus(item)
                return (
                  <li key={item.id} className="exam-case-item">
                    <span className="resource-icon" aria-hidden="true"><FileText size={18} /></span>
                    <div className="exam-case-details">
                      <strong>{item.filename}</strong>
                      <p>{item.page_count} {item.page_count === 1 ? 'page' : 'pages'} · {item.usable_page_count} usable</p>
                      <p>{answerLabel(item)}</p>
                    </div>
                    <div className="exam-case-actions">
                      <span className={`case-status is-${status.tone}`}>{status.label}</span>
                      <button
                        type="button"
                        className="button small secondary resource-delete"
                        aria-label={`Delete ${item.filename}`}
                        disabled={busy || demo}
                        onClick={() => setRemove(item)}
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : loading ? (
            <Loading text="Loading exam cases…" />
          ) : !listError && (
            <div className="resource-empty">
              <span className="resource-icon" aria-hidden="true"><FileText size={24} /></span>
              <strong>{demo ? 'Exam cases are available in your courses' : 'No exam cases yet'}</strong>
              <p>{demo ? 'Open one of your courses to upload a sample exam.' : 'Add a sample exam PDF to get started.'}</p>
            </div>
          )}
        </section>

        {!demo && (
          <form className="panel resource-panel" onSubmit={upload} noValidate aria-busy={operation === 'upload'}>
            <div className="resource-panel-heading"><h3>Add an exam case</h3></div>
            <CasePdfInput label="Choose exam case PDF" file={file} disabled={busy} onChange={setFile} />

            <fieldset className="resource-fieldset" disabled={busy}>
              <legend>Where are the answers?</legend>
              <div className="case-answer-options">
                {answerOptions.map(([mode, label]) => (
                  <label key={mode} className="resource-choice">
                    <input
                      type="radio"
                      name="answer_mode"
                      value={mode}
                      checked={answerMode === mode}
                      onChange={() => {
                        setAnswerMode(mode)
                        if (mode !== 'file') setAnswerFile(null)
                      }}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            {answerMode === 'file' && (
              <CasePdfInput label="Choose answer PDF" file={answerFile} disabled={busy} onChange={setAnswerFile} />
            )}

            <div className="resource-form-footer">
              <button type="submit" className="button" disabled={busy || !file || (answerMode === 'file' && !answerFile)}>
                <Upload size={16} aria-hidden="true" />
                {operation === 'upload' ? 'Uploading…' : 'Upload exam case'}
              </button>
            </div>
          </form>
        )}
      </div>

      <Modal
        open={Boolean(remove)}
        title="Delete exam case?"
        closeable={!busy}
        onClose={() => setRemove(null)}
      >
        <div className="resource-delete-files">
          <span className="resource-icon" aria-hidden="true"><FileText size={20} /></span>
          <div>
            <strong>{remove?.filename}</strong>
            {remove?.answer_file && <small>Answer PDF · {remove.answer_file.filename}</small>}
          </div>
        </div>
        <div className="actions resource-modal-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={() => setRemove(null)}>
            Cancel
          </button>
          <button type="button" className="button danger" disabled={busy} onClick={() => void confirmDelete()}>
            {operation === 'delete' ? 'Deleting…' : 'Delete exam case'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
