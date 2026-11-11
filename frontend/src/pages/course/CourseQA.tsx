import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUpRight, Check, History, MessageSquare } from 'lucide-react'

import type {
  CourseDetail,
  QAResponse,
} from './types'

import { askCourse, listQuestions } from './api'
import { messageOf } from '../../shared/request'
import { Link } from '../../shared/router'

import {
  Notice,
  Sources,
} from '../../shared/components/UI'

export default function CourseQA({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const demo = courseId === 'demo'

  const usable =
    course.documents.some(
      (material) =>
        material.ingest_status ===
          'complete' &&
        material.usable_page_count > 0,
    )

  const [question, setQuestion] =
    useState('')

  const [records, setRecords] = useState<
    {
      question: string
      response: QAResponse
    }[]
  >([])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] =
    useState<number | null>(null)

  const historyRecords = [...records].sort(
    (a, b) => b.response.qa_id - a.response.qa_id,
  )
  const selectedRecord =
    historyRecords.find(
      (record) => record.response.qa_id === selectedId,
    ) ?? historyRecords[0] ?? null
  const displayedRecords =
    !demo && selectedRecord ? [selectedRecord] : []

  useEffect(() => {
    if (demo) return
    let active = true
    listQuestions(course.id)
      .then((rows) => {
        if (!active) return
        setRecords(
          rows.map((row) => ({
            question: row.question || '',
            response: row,
          })),
        )
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [course.id, demo])

  async function submit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (busy || !usable || demo) return

    const text = question.trim()

    if (
      !text ||
      Array.from(text).length > 2000
    ) {
      setError(
        'Enter a question of 1–2,000 characters.',
      )
      return
    }

    setBusy(true)
    setError('')

    try {
      const response = await askCourse(
        course.id,
        text,
      )

      setRecords((current) => [
        {
          question: text,
          response,
        },
        ...current,
      ])
      setSelectedId(response.qa_id)

      setQuestion('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qa-page stack">
      <section className="panel qa-question">
        <h2>Ask your course materials</h2>

        <p className="muted">
          Answers use this course’s uploaded
          PDFs and include source references.
          Questions do not change your
          practice scores.
        </p>

        {demo && (
          <Notice>
            Live Q&A is available in real
            courses. This demo shows a fixed
            example only; submitting questions
            is disabled.
          </Notice>
        )}

        {!usable && (
          <Notice>
            No usable material is available.
            {' '}
            <Link
              href={
                `/courses/${courseId}/info`
              }
            >
              Upload a readable PDF first
            </Link>.
          </Notice>
        )}

        <form
          className="stack"
          noValidate
          onSubmit={submit}
        >
          <label className="field">
            <span>Your question</span>

            <textarea
              rows={4}
              value={question}
              maxLength={2000}
              disabled={busy || demo}
              onChange={(event) => {
                setQuestion(
                  event.target.value,
                )
                setError('')
              }}
              placeholder="What does this lecture say about breadth-first search?"
            />
          </label>

          {error && (
            <Notice tone="error">
              {error}
            </Notice>
          )}

          <div className="actions">
            <button
              className="button"
              disabled={
                busy || !usable || demo
              }
            >
              {busy
                ? 'Searching your materials…'
                : 'Ask question'}
            </button>

            <small className="muted">
              Earlier questions stay on this page after you refresh.
            </small>
          </div>
        </form>
      </section>

      <aside
        className="panel qa-history"
        aria-labelledby="qa-history-title"
      >
        <header className="qa-history-header">
          <div className="qa-history-heading">
            <span className="qa-history-heading-icon" aria-hidden="true">
              <History size={18} strokeWidth={1.7} />
            </span>
            <h2 id="qa-history-title">Q&A history</h2>
            {!demo && (
              <span className="qa-history-count">
                {historyRecords.length}
              </span>
            )}
          </div>
          <p className="qa-history-description">
            Your questions, newest first.
          </p>
        </header>

        {demo ? (
          <div className="qa-history-empty">
            <MessageSquare size={24} strokeWidth={1.5} aria-hidden="true" />
            <p>History is available in real courses.</p>
          </div>
        ) : historyRecords.length === 0 ? (
          <div className="qa-history-empty">
            <MessageSquare size={24} strokeWidth={1.5} aria-hidden="true" />
            <strong>A place for your questions</strong>
            <p>Ask your first question to start your history.</p>
          </div>
        ) : (
          <ul className="qa-history-list">
            {historyRecords.map((record, index) => {
              const id = record.response.qa_id
              const selected =
                selectedRecord?.response.qa_id === id

              return (
                <li key={id}>
                  <button
                    type="button"
                    className={
                      `qa-history-item${selected ? ' is-selected' : ''}`
                    }
                    aria-pressed={selected}
                    aria-controls="qa-answer-panel"
                    onClick={() => setSelectedId(id)}
                  >
                    <span className="qa-history-item-heading">
                      <span className="qa-history-item-label">
                        {index === 0 ? 'Latest question' : 'Earlier question'}
                      </span>
                      {selected && (
                        <span className="qa-history-selected-icon" aria-hidden="true">
                          <Check size={12} strokeWidth={2.5} />
                        </span>
                      )}
                    </span>
                    <span className="qa-history-question">
                      {record.question || 'Untitled question'}
                    </span>
                    <span className="qa-history-preview">
                      {record.response.answer}
                    </span>
                    <span className="qa-history-meta">
                      <span>
                        {selected ? 'Currently viewing' : 'View answer'}
                      </span>
                      <ArrowUpRight size={14} aria-hidden="true" />
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </aside>

      {demo && (
        <section className="panel qa-answer">
          <span className="badge">
            Fixed example
          </span>

          <h3>What is a binary tree?</h3>

          <p>
            A binary tree is a tree in which a
            node has at most two children,
            conventionally called left and
            right.
          </p>

          <Sources
            sources={[
              {
                document_id: 101,
                filename:
                  'Algorithms-L6.pdf',
                page_number: 2,
              },
            ]}
          />
        </section>
      )}

      {!demo && !selectedRecord && (
        <section id="qa-answer-panel" className="panel qa-empty">
          <h3>Your answer will appear here</h3>
          <p className="muted">
            Ask a question above, or select a saved question
            from the history to view its answer.
          </p>
        </section>
      )}

      {displayedRecords.map((record) => (
        <section
          id="qa-answer-panel"
          className="panel qa-answer"
          key={record.response.qa_id}
          aria-label="Selected question and answer"
        >
          <p className="eyebrow">
            Your question
          </p>

          <h3>{record.question}</h3>

          <span
            className={
              `badge ${
                record.response.refused
                  ? 'warning'
                  : ''
              }`
            }
          >
            {record.response.refused
              ? 'Insufficient evidence'
              : record.response.origin === 'account'
                ? 'Answer from your account'
                : record.response.origin === 'chat'
                  ? 'Noted'
                  : record.response.web_sources?.length
                  ? 'Supplemented from the web'
                  : record.response.cited_pages.length
                    ? 'Answer from your materials'
                    : 'Answer from your study record'}
          </span>

          <p className="answer-text">
            {record.response.answer}
          </p>

          <Sources
            sources={
              record.response.cited_pages
            }
          />

          {record.response.web_sources?.map(
            (source) => (
              <a
                key={source.url}
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                Web: {source.title}
              </a>
            ),
          )}

          <small className="muted">
            Record {record.response.qa_id}
            {' · '}
            {record.response.course_name}
          </small>
        </section>
      ))}
    </div>
  )
}
