import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Globe, Plus, Trash2 } from 'lucide-react'

import type {
  CourseDetail,
  QAResponse,
} from './types'

import AnswerBody from './AnswerBody'
import { askCourse, deleteQuestionTab, listQuestions } from './api'
import { usableMaterials } from './DocumentPicker'
import QaPdfChip from './QaPdfChip'
import { messageOf } from '../../shared/request'
import { Link } from '../../shared/router'

import {
  Notice,
  Sources,
} from '../../shared/components/UI'

type Tab = {
  tab_id: string
  tab_title: string
  messages: QAResponse[]
  draft: boolean
}

function newTabId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `tab-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function groupTabs(rows: QAResponse[]): Tab[] {
  const order: string[] = []
  const byId = new Map<string, Tab>()
  const chronological = [...rows].sort(
    (a, b) => (a.qa_id || 0) - (b.qa_id || 0),
  )
  for (const row of chronological) {
    const tabId = row.tab_id || `legacy-${row.qa_id}`
    let tab = byId.get(tabId)
    if (!tab) {
      tab = {
        tab_id: tabId,
        tab_title: row.tab_title || row.question || 'Chat',
        messages: [],
        draft: false,
      }
      byId.set(tabId, tab)
      order.push(tabId)
    }
    tab.messages.push(row)
  }
  return order
    .map((id) => byId.get(id)!)
    .sort((a, b) => {
      const aLast = a.messages.at(-1)?.qa_id || 0
      const bLast = b.messages.at(-1)?.qa_id || 0
      return bLast - aLast
    })
}

function answerBadge(response: QAResponse) {
  if (response.refused) return 'Insufficient evidence'
  if (response.origin === 'account') return 'Answer from your account'
  if (response.origin === 'chat') return 'Noted'
  if (response.web_sources?.length) return 'Supplemented from the web'
  if (response.cited_pages.length) return 'Answer from your materials'
  return 'Answer from your study record'
}

export default function CourseQA({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const demo = courseId === 'demo'
  const materials = usableMaterials(course.documents)
  const usable = materials.length > 0

  const [question, setQuestion] = useState('')
  const [documentIds, setDocumentIds] = useState<number[]>(
    () => materials.map((material) => material.id),
  )
  const [includeWeb, setIncludeWeb] = useState(false)
  const [tabs, setTabs] = useState<Tab[]>([])
  const [activeTabId, setActiveTabId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const readyIds = new Set(materials.map((material) => material.id))
    setDocumentIds((current) => {
      if (!current.length) return []
      const kept = current.filter((id) => readyIds.has(id))
      return kept
    })
  }, [course.documents])

  useEffect(() => {
    if (demo) return
    let active = true
    listQuestions(course.id)
      .then((rows) => {
        if (!active) return
        const loaded = groupTabs(rows)
        if (!loaded.length) {
          const id = newTabId()
          setTabs([
            {
              tab_id: id,
              tab_title: 'New chat',
              messages: [],
              draft: true,
            },
          ])
          setActiveTabId(id)
          return
        }
        setTabs(loaded)
        setActiveTabId(loaded[0].tab_id)
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [course.id, demo])

  const activeTab = useMemo(
    () => tabs.find((tab) => tab.tab_id === activeTabId) ?? null,
    [tabs, activeTabId],
  )

  useEffect(() => {
    const node = bottomRef.current
    if (!node) return
    node.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [activeTabId, activeTab?.messages.length, busy, activeTab?.messages.at(-1)?.answer])

  function openNewChat() {
    const id = newTabId()
    setTabs((current) => [
      {
        tab_id: id,
        tab_title: 'New chat',
        messages: [],
        draft: true,
      },
      ...current.filter((tab) => !(tab.draft && !tab.messages.length)),
    ])
    setActiveTabId(id)
    setQuestion('')
    setError('')
  }

  function removeTabLocally(tabId: string) {
    setTabs((current) => {
      const next = current.filter((tab) => tab.tab_id !== tabId)
      if (!next.length) {
        const id = newTabId()
        queueMicrotask(() => setActiveTabId(id))
        return [
          {
            tab_id: id,
            tab_title: 'New chat',
            messages: [],
            draft: true,
          },
        ]
      }
      if (activeTabId === tabId) {
        const fallback = next[0].tab_id
        queueMicrotask(() => setActiveTabId(fallback))
      }
      return next
    })
    setQuestion('')
    setError('')
  }

  async function removeChat(tab: Tab) {
    if (busy || deletingId || demo) return
    if (tab.draft || !tab.messages.length) {
      removeTabLocally(tab.tab_id)
      return
    }
    setDeletingId(tab.tab_id)
    setError('')
    try {
      await deleteQuestionTab(course.id, tab.tab_id)
      removeTabLocally(tab.tab_id)
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setDeletingId('')
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || demo || !activeTab) return
    const text = question.trim()
    if (!text || Array.from(text).length > 2000) {
      setError('Enter a question of 1–2,000 characters.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const response = await askCourse(
        course.id,
        text,
        documentIds,
        activeTab.tab_id,
        includeWeb,
      )
      const tabId = response.tab_id || activeTab.tab_id
      setTabs((current) => {
        const others = current.filter(
          (tab) => tab.tab_id !== activeTab.tab_id && tab.tab_id !== tabId,
        )
        const existing =
          current.find((tab) => tab.tab_id === tabId) ||
          current.find((tab) => tab.tab_id === activeTab.tab_id)
        const messages = [
          ...(existing?.messages || []).filter(
            (item) => item.qa_id !== response.qa_id,
          ),
          response,
        ]
        const next: Tab = {
          tab_id: tabId,
          tab_title:
            existing?.tab_title && existing.tab_title !== 'New chat'
              ? existing.tab_title
              : response.tab_title || text.slice(0, 72),
          messages,
          draft: false,
        }
        return [next, ...others]
      })
      setActiveTabId(tabId)
      setQuestion('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  const lastPreview = (tab: Tab) => {
    const last = tab.messages.at(-1)
    if (!last) return 'Empty chat'
    return last.answer?.slice(0, 120) || last.question || ''
  }

  return (
    <div className="qa-page stack">
      <aside className="qa-history" aria-labelledby="qa-tabs-title">
        <header className="qa-history-header">
          <div className="qa-history-heading">
            <h2 id="qa-tabs-title">Chats</h2>
            {!demo && (
              <button
                type="button"
                className="qa-history-new"
                onClick={openNewChat}
                title="New chat"
              >
                <Plus size={15} strokeWidth={2} />
                <span>New</span>
              </button>
            )}
          </div>
        </header>

        {demo ? (
          <div className="qa-history-empty">
            <p>Chats are available in real courses.</p>
          </div>
        ) : tabs.length === 0 ? (
          <div className="qa-history-empty">
            <p>Ask a question to start a chat.</p>
          </div>
        ) : (
          <ul className="qa-history-list">
            {tabs.map((tab) => {
              const selected = tab.tab_id === activeTabId
              const removing = deletingId === tab.tab_id
              return (
                <li key={tab.tab_id}>
                  <div
                    className={
                      `qa-history-item${selected ? ' is-selected' : ''}`
                    }
                  >
                    <button
                      type="button"
                      className="qa-history-open"
                      aria-pressed={selected}
                      onClick={() => {
                        setActiveTabId(tab.tab_id)
                        setError('')
                      }}
                    >
                      <span className="qa-history-question">
                        {tab.tab_title || 'New chat'}
                      </span>
                      <span className="qa-history-preview">
                        {tab.messages.length > 1
                          ? `${tab.messages.length} turns`
                          : lastPreview(tab)}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="qa-history-delete"
                      aria-label={`Delete ${tab.tab_title || 'chat'}`}
                      title="Delete chat"
                      disabled={busy || Boolean(deletingId)}
                      onClick={() => {
                        void removeChat(tab)
                      }}
                    >
                      <Trash2 size={14} strokeWidth={1.8} />
                      <span className="sr-only">
                        {removing ? 'Deleting…' : 'Delete'}
                      </span>
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </aside>

      <div className="qa-main">
        <div className="qa-thread" aria-label="Conversation">
          {demo && (
            <section className="panel qa-answer">
              <span className="badge">Fixed example</span>
              <h3>What is a binary tree?</h3>
              <p>
                A binary tree is a tree in which a node has at most two children,
                conventionally called left and right.
              </p>
              <Sources
                sources={[
                  {
                    document_id: 101,
                    filename: 'Algorithms-L6.pdf',
                    page_number: 2,
                  },
                ]}
              />
            </section>
          )}

          {!demo && activeTab && activeTab.messages.length > 0 && (
            activeTab.messages.map((message) => (
              <section
                className="panel qa-answer"
                key={message.qa_id}
              >
                <p className="eyebrow">Your question</p>
                <h3>{message.question || 'Question'}</h3>
                <span
                  className={`badge ${message.refused ? 'warning' : ''}`}
                >
                  {answerBadge(message)}
                </span>
                <AnswerBody text={message.answer} />
                <Sources courseId={courseId} sources={message.cited_pages} />
                {message.web_sources?.map((source) => (
                  <a
                    key={source.url}
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Web: {source.title}
                  </a>
                ))}
              </section>
            ))
          )}

          {!demo && activeTab && !activeTab.messages.length && !busy && (
            <section className="panel qa-empty">
              <h3>Your conversation will appear here</h3>
              <p className="muted">
                Ask a first question, then keep going with follow-ups in this chat.
              </p>
            </section>
          )}

          {busy && (
            <section className="panel qa-answer qa-pending" aria-live="polite">
              <p className="eyebrow">Working</p>
              <h3>Thinking…</h3>
              <p className="muted">Preparing a reply for this chat.</p>
            </section>
          )}

          <div ref={bottomRef} className="qa-thread-end" aria-hidden="true" />
        </div>

        <section className="panel qa-question">
          {demo && (
            <Notice>
              Live Q&A is available in real courses. This demo shows a fixed
              example only.
            </Notice>
          )}

          {!usable && (
            <Notice>
              No lecture PDFs are ready yet, so replies stay casual chat. You can
              still turn on Web search. Upload materials on{' '}
              <Link href={`/courses/${courseId}/info`}>
                Course information
              </Link>{' '}
              when you want grounded answers from notes.
            </Notice>
          )}

          {error && <Notice tone="error">{error}</Notice>}

          {!demo && (
            <form className="qa-composer" noValidate onSubmit={submit}>
              <div className="qa-composer-attachments">
                <QaPdfChip
                  documents={course.documents}
                  selectedIds={documentIds}
                  disabled={busy}
                  onChange={(ids) => {
                    setDocumentIds(ids)
                    setError('')
                  }}
                />
                <button
                  type="button"
                  className={`qa-web-chip${includeWeb ? ' is-on' : ''}`}
                  disabled={busy}
                  aria-pressed={includeWeb}
                  title={
                    includeWeb
                      ? 'Web search on — each ask also searches the public web once'
                      : 'Web search off — turn on to also search the web each ask'
                  }
                  onClick={() => {
                    setIncludeWeb((value) => !value)
                    setError('')
                  }}
                >
                  <Globe size={14} strokeWidth={1.8} />
                  <span>Web</span>
                </button>
                {!documentIds.length && !includeWeb && (
                  <span className="muted small">
                    No PDF selected — casual chat. Turn on Web to search online.
                  </span>
                )}
                {includeWeb && (
                  <span className="muted small">
                    Web on — each ask also searches once online
                    {!documentIds.length ? ' (no PDF needed).' : '.'}
                  </span>
                )}
              </div>

              <div className="qa-composer-row">
                <textarea
                  className="qa-composer-input"
                  rows={2}
                  value={question}
                  maxLength={2000}
                  disabled={busy}
                  onChange={(event) => {
                    setQuestion(event.target.value)
                    setError('')
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter' || event.shiftKey) return
                    if (event.nativeEvent.isComposing) return
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }}
                  placeholder={
                    !documentIds.length
                      ? includeWeb
                        ? 'Ask anything… (casual chat + web search)'
                        : 'Say something… (no PDF — casual chat, or turn on Web)'
                      : activeTab?.messages.length
                        ? 'Ask a follow-up…'
                        : 'Ask anything about your course materials…'
                  }
                />

                <div className="qa-composer-actions">
                  {activeTab?.messages.length ? (
                    <button
                      type="button"
                      className="button small secondary"
                      disabled={busy}
                      onClick={openNewChat}
                    >
                      New chat
                    </button>
                  ) : null}
                  <button
                    className="button small"
                    disabled={busy}
                  >
                    {busy ? '…' : 'Send'}
                  </button>
                </div>
              </div>
            </form>
          )}
        </section>
      </div>
    </div>
  )
}
