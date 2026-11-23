import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { FileText, Globe } from 'lucide-react'

import AnswerBody from './AnswerBody'
import { askCourse, documentFileUrl, listQuestions } from './api'
import type { QAResponse } from './types'
import { messageOf } from '../../shared/request'
import { Notice } from '../../shared/components/UI'

function readingTabId(taskId: string) {
  return `read-${taskId}`.slice(0, 64)
}

export default function ReadingTutor({
  courseId,
  taskId,
  document,
}: {
  courseId: number
  taskId: string
  document: { document_id: number; filename: string; page_count?: number } | null
}) {
  const tabId = readingTabId(taskId)
  const [pageScope, setPageScope] = useState<{ documentId: number; value: string }>()
  const page = pageScope?.documentId === document?.document_id ? pageScope?.value ?? '' : ''
  const [messages, setMessages] = useState<QAResponse[]>([])
  const [question, setQuestion] = useState('')
  const [includeWeb, setIncludeWeb] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    listQuestions(courseId)
      .then((rows) => {
        if (!active) return
        setMessages(
          rows
            .filter((row) => row.tab_id === tabId)
            .sort((a, b) => (a.qa_id || 0) - (b.qa_id || 0)),
        )
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [courseId, tabId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, busy])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !document) return
    const text = question.trim()
    if (!text || Array.from(text).length > 2000) {
      setError('Enter a question of 1–2,000 characters.')
      return
    }
    const pageNumber = page ? Number(page) : undefined
    if (pageNumber !== undefined && (
      !Number.isInteger(pageNumber) || pageNumber < 1 || (document.page_count && pageNumber > document.page_count)
    )) {
      setError('Enter a valid page number for this PDF.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const response = await askCourse(
        courseId,
        text,
        [document.document_id],
        tabId,
        includeWeb,
        true,
        pageNumber,
      )
      setMessages((current) => [
        ...current.filter((item) => item.qa_id !== response.qa_id),
        response,
      ])
      setQuestion('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="reading-tutor" aria-label="Chat">
      <div className="qa-thread reading-tutor-thread">
        {!messages.length && !busy && (
          <section className="qa-empty">
            <h3>Ask about this PDF</h3>
            <p className="muted">Ask a question, request a document summary, or enter a page number to focus on one page.</p>
          </section>
        )}
        {messages.map((message) => (
          <section className="reading-turn" key={message.qa_id}>
            <p className="eyebrow">You</p>
            <h3>{message.question || 'Question'}</h3>
            <AnswerBody text={message.answer} />
            {(message.cited_pages.length > 0 || Boolean(message.web_sources?.length)) && (
              <div className="source-list" aria-label="Answer sources">
                {message.cited_pages.map(source => (
                  <a
                    className="source-chip"
                    key={source.document_id + '-' + source.page_number}
                    href={documentFileUrl(courseId, source.document_id) + '#page=' + source.page_number}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <FileText size={12} aria-hidden="true" />
                    {source.filename} · p. {source.page_number}
                  </a>
                ))}
                {message.web_sources?.map(source => (
                  <a className="source-chip" key={source.url} href={source.url} target="_blank" rel="noreferrer">
                    Web · {source.title}
                  </a>
                ))}
              </div>
            )}
          </section>
        ))}
        {busy && (
          <section className="reading-turn" aria-live="polite">
            <p className="eyebrow">Working</p>
            <h3>Thinking…</h3>
          </section>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <div ref={bottomRef} />
      </div>
      <form className="qa-composer reading-tutor-composer" noValidate onSubmit={(event) => void submit(event)}>
        <div className="qa-composer-attachments">
          <span className="qa-pdf-chip" title={document?.filename ?? 'No PDF selected'}>
            <FileText size={14} strokeWidth={1.8} />
            <span className="qa-pdf-chip-label">{document?.filename ?? 'No PDF selected'}</span>
          </span>
          <button
            type="button"
            className={`qa-web-chip${includeWeb ? ' is-on' : ''}`}
            disabled={busy}
            aria-pressed={includeWeb}
            title={includeWeb ? 'Web search on' : 'Web search off'}
            onClick={() => setIncludeWeb((value) => !value)}
          >
            <Globe size={14} strokeWidth={1.8} />
            <span>Web</span>
          </button>
        </div>
        {document && (
          <label className="reading-tutor-page small">
            PDF page
            <input
              type="number"
              min={1}
              max={document.page_count || undefined}
              step={1}
              value={page}
              disabled={busy}
              placeholder="All pages"
              onChange={event => {
                setPageScope({ documentId: document.document_id, value: event.target.value })
                setError('')
              }}
            />
          </label>
        )}
        <div className="qa-composer-row">
          <textarea
            className="qa-composer-input"
            rows={2}
            value={question}
            maxLength={2000}
            disabled={busy || !document}
            placeholder={messages.length ? 'Ask a follow-up…' : 'Ask about this PDF…'}
            onChange={(event) => {
              setQuestion(event.target.value)
              setError('')
            }}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
              if (event.shiftKey) return
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }}
          />
          <button className="button" disabled={busy || !document || !question.trim()}>
            {busy ? 'Thinking…' : 'Ask'}
          </button>
        </div>
        <p className="muted small qa-composer-hint">Press Enter to send; Shift+Enter adds a new line.</p>
      </form>
    </section>
  )
}
