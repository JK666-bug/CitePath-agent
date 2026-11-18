import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { FileText } from 'lucide-react'

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
  Modal,
  Notice,
} from '../../shared/components/UI'

export default function CourseExamCases({
  courseId,
}: {
  courseId: string
  course?: unknown
}) {
  const demo = courseId === 'demo'
  const numericId = Number(courseId)

  const [cases, setCases] = useState<ExamCase[]>([])
  const [loading, setLoading] = useState(!demo)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [answerFile, setAnswerFile] = useState<File | null>(null)
  const [answerMode, setAnswerMode] =
    useState<ExamCaseAnswerMode>('none')
  const [remove, setRemove] = useState<ExamCase | null>(null)

  async function reload() {
    if (demo) {
      setCases([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const response = await listExamCases(numericId)
      setCases(response.cases)
      setError('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [courseId])

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
    setBusy(true)
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
      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (!remove || busy || demo) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteExamCase(numericId, remove.id)
      await reload()
      setMessage('Exam case removed.')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
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
        : 'Answer file missing'
    }
    return 'No answers'
  }

  return (
    <div className="stack">
      <section className="panel">
        <h2>Exam cases</h2>
        <p className="muted">
          Upload sample exams for style. They stay separate from lecture
          PDFs and are not used for plan chapters or Q&amp;A retrieval.
        </p>
      </section>

      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice>{message}</Notice>}

      <section className="panel">
        <h2>Uploaded cases</h2>
        {loading ? (
          <p className="muted">Loading exam cases…</p>
        ) : cases.length ? (
          <ul className="materials-list">
            {cases.map((item) => (
              <li key={item.id}>
                <FileText size={18} strokeWidth={1.4} />
                <div>
                  <strong>{item.filename}</strong>
                  <p>
                    {item.page_count} pages · {item.usable_page_count}{' '}
                    usable · {answerLabel(item)}
                  </p>
                </div>
                <span className="badge">
                  {item.ingest_status === 'complete'
                    ? 'Ready'
                    : item.ingest_status === 'pending'
                      ? 'Processing'
                      : 'Unavailable'}
                </span>
                <button
                  className="button small danger"
                  disabled={busy || demo}
                  onClick={() => setRemove(item)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No exam cases uploaded yet.</p>
        )}

        {demo ? (
          <p className="muted small">
            Sample courses do not store real exam-case PDFs.
          </p>
        ) : (
          <form className="stack" onSubmit={upload} noValidate>
            <label className="stack">
              <span>Exam-case PDF</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={busy}
                onChange={(event) =>
                  setFile(event.target.files?.[0] ?? null)
                }
              />
            </label>

            <fieldset className="stack">
              <legend>Answer status</legend>
              {(
                [
                  ['none', 'No answers'],
                  ['in_case', 'Answers are in the case PDF'],
                  ['file', 'Separate answer PDF'],
                ] as const
              ).map(([mode, label]) => (
                <label key={mode} className="practice-prefs-check">
                  <input
                    type="radio"
                    name="answer_mode"
                    value={mode}
                    checked={answerMode === mode}
                    disabled={busy}
                    onChange={() => {
                      setAnswerMode(mode)
                      if (mode !== 'file') {
                        setAnswerFile(null)
                      }
                    }}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </fieldset>

            {answerMode === 'file' && (
              <label className="stack">
                <span>Answer PDF</span>
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  disabled={busy}
                  onChange={(event) =>
                    setAnswerFile(event.target.files?.[0] ?? null)
                  }
                />
              </label>
            )}

            <div className="actions">
              <button
                className="button"
                disabled={busy || !file}
              >
                {busy ? 'Processing…' : 'Upload exam case'}
              </button>
            </div>
          </form>
        )}
      </section>

      <Modal
        open={Boolean(remove)}
        title="Delete this exam case?"
        closeable={!busy}
        onClose={() => setRemove(null)}
      >
        <p>
          Delete {remove?.filename}
          {remove?.answer_file
            ? ` and its answer file ${remove.answer_file.filename}`
            : ''}
          ?
        </p>
        <div className="actions">
          <button
            className="button danger"
            disabled={busy}
            onClick={() => {
              void confirmDelete()
            }}
          >
            {busy ? 'Deleting…' : 'Delete exam case'}
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setRemove(null)}
          >
            Cancel
          </button>
        </div>
      </Modal>
    </div>
  )
}
