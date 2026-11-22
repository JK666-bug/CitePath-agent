import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { FileText, Globe } from 'lucide-react'

import AnswerBody from './AnswerBody'
import { askCourse, listQuestions } from './api'
import type { QAResponse, Source } from './types'
import { messageOf } from '../../shared/request'
import { Notice } from '../../shared/components/UI'

function readingTabId(taskId: string) {
  return `read-${taskId}`.slice(0, 64)
}

export default function ReadingTutor({
  courseId,
  taskId,
  sources,
}: {
  courseId: number
  taskId: string
  sources: Source[]
}) {
  const tabId = readingTabId(taskId)
  const documentIds = useMemo(
    () => [...new Set(sources.map((source) => source.document_id))],
    [sources],
  )
  const filenames = useMemo(() => {
    const names: string[] = []
    const seen = new Set<number>()
    for (const source of sources) {
      if (seen.has(source.document_id)) continue
      seen.add(source.document_id)
      names.push(source.filename)
    }
    return names
  }, [sources])
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
    if (busy) return
    const text = question.trim()
    if (!text || Array.from(text).length > 2000) {
      setError('Enter a question of 1–2,000 characters.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const response = await askCourse(
        courseId,
        text,
        documentIds,
        tabId,
        includeWeb,
        true,
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

  const attachment =
    filenames.length === 0
      ? 'No PDF'
      : filenames.length === 1
        ? filenames[0]
        : `${filenames.length} PDFs`

  return (
    <section className="reading-tutor" aria-label="Chat">
      <div className="qa-thread reading-tutor-thread">
        {!messages.length && !busy && (
          <section className="qa-empty">
            <h3>Ask anything</h3>
            <p className="muted">This chat already has the lecture PDF attached. Turn on Web if you also want a web search.</p>
          </section>
        )}
        {messages.map((message) => (
          <section className="reading-turn" key={message.qa_id}>
            <p className="eyebrow">You</p>
            <h3>{message.question || 'Question'}</h3>
            <AnswerBody text={message.answer} />
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
          <span className="qa-pdf-chip" title={filenames.join(', ') || 'No PDF attached'}>
            <FileText size={14} strokeWidth={1.8} />
            <span className="qa-pdf-chip-label">{attachment}</span>
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
        <div className="qa-composer-row">
          <textarea
            className="qa-composer-input"
            rows={2}
            value={question}
            maxLength={2000}
            disabled={busy}
            placeholder={messages.length ? 'Ask a follow-up…' : 'Ask anything…'}
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
          <button className="button" disabled={busy || !question.trim()}>
            {busy ? 'Thinking…' : 'Ask'}
          </button>
        </div>
        <p className="muted small qa-composer-hint">Press Enter to send; Shift+Enter adds a new line.</p>
      </form>
    </section>
  )
}
