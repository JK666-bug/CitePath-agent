import {
  useEffect,
  useId,
  useRef,
  useState,
} from 'react'

import type { ReactNode } from 'react'

import {
  FileText,
  LoaderCircle,
  X,
} from 'lucide-react'

import type { MaterialInventory, Source } from '../../pages/course/types'
import { getDocumentInventory } from '../../pages/course/api'
import { messageOf } from '../request'
import { Link } from '../router'

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && (
          <p className="eyebrow">{eyebrow}</p>
        )}

        <h1>{title}</h1>

        {subtitle && (
          <p className="muted">{subtitle}</p>
        )}
      </div>

      {actions && (
        <div className="actions">
          {actions}
        </div>
      )}
    </header>
  )
}

export function Notice({
  children,
  tone = 'info',
}: {
  children: ReactNode
  tone?: 'info' | 'error' | 'success'
}) {
  return (
    <div
      className={`notice notice-${tone}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      {children}
    </div>
  )
}

export function DemoNotice() {
  return (
    <Notice>
      <strong>Interface demo.</strong>{' '}
      Sample materials and questions are fixed.
      No PDF analysis, AI generation, or model
      grading is performed. Changes are stored
      only in this browser.
    </Notice>
  )
}

export function Loading({
  text = 'Loading your study space…',
}: {
  text?: string
}) {
  return (
    <div
      className="loading-state"
      role="status"
    >
      <LoaderCircle
        className="spin"
        size={20}
      />

      {text}
    </div>
  )
}

export function Empty({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <section className="empty-state">
      <FileText
        size={28}
        strokeWidth={1.3}
      />

      <h2>{title}</h2>

      {children && (
        <div className="muted">
          {children}
        </div>
      )}
    </section>
  )
}

export function Modal({
  open,
  title,
  onClose,
  children,
  closeable = true,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  closeable?: boolean
}) {
  const ref =
    useRef<HTMLDialogElement>(null)

  const heading = useId()

  useEffect(() => {
    if (open && !ref.current?.open) {
      ref.current?.showModal()
    }

    if (!open && ref.current?.open) {
      ref.current.close()
    }
  }, [open])

  return (
    <dialog
      className="cp-modal"
      ref={ref}
      aria-labelledby={heading}
      onCancel={(event) => {
        event.preventDefault()

        if (closeable) {
          onClose()
        }
      }}
      onClick={(event) => {
        if (
          closeable &&
          event.target === event.currentTarget
        ) {
          onClose()
        }
      }}
    >
      <div className="modal-content">
        <header>
          <h2 id={heading}>{title}</h2>

          {closeable && (
            <button
              type="button"
              className="icon-button"
              aria-label="Close dialog"
              onClick={onClose}
            >
              <X size={18} />
            </button>
          )}
        </header>

        {open && children}
      </div>
    </dialog>
  )
}

export function Sources({
  sources,
  courseId,
}: {
  sources: Source[]
  courseId?: string | number
}) {
  const [selected, setSelected] =
    useState<Source | null>(null)
  const [document, setDocument] = useState<MaterialInventory | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')
  const lookup = useRef(0)

  async function inspect(source: Source) {
    const requestId = ++lookup.current
    setSelected(source)
    setDocument(null)
    setError('')
    if (!courseId || courseId === 'demo') return
    setChecking(true)
    try {
      const inventory = await getDocumentInventory(Number(courseId))
      if (lookup.current === requestId) setDocument(inventory.documents.find((item) => item.id === source.document_id) ?? null)
    } catch (reason) {
      if (lookup.current === requestId) setError(messageOf(reason))
    } finally {
      if (lookup.current === requestId) setChecking(false)
    }
  }

  return (
    <>
      <div className="source-list">
        {sources.map((source) => (
          <button
            type="button"
            className="source-chip"
            key={
              `${source.document_id}-` +
              source.page_number
            }
            onClick={() =>
              void inspect(source)
            }
          >
            <FileText size={12} />
            Doc {source.document_id}
            {' · '}
            p. {source.page_number}
          </button>
        ))}
      </div>

      <Modal
        open={Boolean(selected)}
        title="Source reference"
        onClose={() => { lookup.current += 1; setSelected(null); setChecking(false) }}
      >
        {selected && (
          <div className="stack">
            <strong>
              {selected.filename}
            </strong>

            <p>
              Document {selected.document_id}
              {' · '}
              Original PDF page {selected.page_number}
            </p>

            {courseId && courseId !== 'demo' ? checking ? (
              <p role="status">Checking source availability…</p>
            ) : error ? (
              <Notice tone="error">{error} <button className="text-button" onClick={() => void inspect(selected)}>Retry source lookup</button></Notice>
            ) : !document ? (
              <Notice>Original source unavailable. No retained material matches this saved document ID. Another upload cannot replace this historical reference.</Notice>
            ) : (
              <>
              {!document.active && <Notice>Archived material. It is excluded from new plans and questions. This saved reference keeps its original document ID.</Notice>}
              {document.original_pdf_available && document.page_numbers.includes(selected.page_number) ? (
              <a
                className="button secondary"
                href={`/api/courses/${courseId}/documents/${selected.document_id}/file#page=${selected.page_number}`}
                target="_blank"
                rel="noreferrer"
              >
                Open original PDF at this page
              </a>
              ) : <Notice>Original PDF or page unavailable. Upload the exact same PDF in Course information to recover this document where its original hash is retained.</Notice>}
              {(!document.active || !document.original_pdf_available) && <Link className="button secondary" href={`/courses/${courseId}/info`}>Manage and restore course materials</Link>}
              </>
            ) : (
              <p className="muted">This reference identifies the original document and PDF page.</p>
            )}
          </div>
        )}
      </Modal>
    </>
  )
}

export function PlanningUnavailable() {
  return (
    <Empty title="Your study plan is not available yet">
      <p>
        Course materials can be saved now.
        The planning service has not been
        connected in the current backend.
      </p>

      <div className="actions centered">
        <Link
          className="button secondary"
          href="/courses/demo/plan"
        >
          Explore the interface demo
        </Link>
      </div>
    </Empty>
  )
}
