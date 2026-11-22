import { useState } from 'react'

import { request } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'

import {
  Modal,
  Notice,
} from '../../shared/components/UI'

type DocumentOption = {
  id: number
  filename: string
  state: 'unplanned' | 'planned' | 'locked'
  eligible: boolean
  reason: string
}

type Options = {
  token: string
  new_documents: DocumentOption[]
  rebuildable_documents: DocumentOption[]
  blocked_documents: DocumentOption[]
}

export default function ChapterRebuild({
  courseId,
  disabled = false,
  onRebuilt,
}: {
  courseId: number
  disabled?: boolean
  onRebuilt: () => void
}) {
  const { loadPlan } = useStudy()

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [options, setOptions] = useState<Options | null>(null)
  const [selected, setSelected] = useState<number[]>([])

  async function api<T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> {
    // Keep conflict explanations visible to the user.
    const response = await fetch(path, {
      ...init,
      credentials: 'include',
    })
    const payload = await response.json().catch(() => null)

    if (!response.ok) {
      throw new Error(
        typeof payload?.detail === 'string'
          ? payload.detail
          : 'Could not update chapters. Please retry.',
      )
    }

    return payload as T
  }

  async function execute(
    current: Options,
    ids: number[],
    confirmed: boolean,
  ) {
    setBusy(true)
    setError('')
    setMessage('')

    try {
      await api(
        `/api/courses/${courseId}/chapters/rebuild`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            token: current.token,
            document_ids: ids,
            confirmed,
          }),
        },
      )

      const updated = await loadPlan(courseId)
      setOptions(null)
      setSelected([])
      if (!updated?.plan?.chapters.length) {
        throw new Error('Chapters were saved. Reload the page to see them.')
      }
      onRebuilt()

    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Could not rebuild chapters.',
      )

      // A conflict must be checked again rather than resubmitted
      // with a stale token.
      setOptions(null)

    } finally {
      setBusy(false)
    }
  }

  async function check() {
    if (busy || disabled) return

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const current = await request<Options>(
        `/api/courses/${courseId}/chapters/options`,
      )

      // Precheck may synchronize historical learning states.
      await loadPlan(courseId)

      if (current.new_documents.length) {
        await execute(
          current,
          current.new_documents.map((item) => item.id),
          false,
        )
        return
      }

      if (!current.rebuildable_documents.length) {
        setMessage(
          'No PDF can be rebuilt. Materials with learning activity are locked; other materials may still be processing.',
        )
        return
      }

      setOptions(current)
      setSelected(
        current.rebuildable_documents.map(
          (item) => item.id,
        ),
      )

    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Could not check the PDFs.',
      )

    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel stack">
      <h2>Chapter outline</h2>

      <p className="muted">
        New PDFs are analyzed first. PDFs with reading,
        practice, or exam activity cannot be rebuilt.
      </p>

      <div className="actions">
        <button
          className="button"
          disabled={busy || disabled}
          onClick={() => void check()}
        >
          {busy ? 'Analyzing…' : 'Rebuild chapters'}
        </button>
      </div>

      {error && (
        <Notice tone="error">{error}</Notice>
      )}

      {message && (
        <Notice>{message}</Notice>
      )}

      <Modal
        open={options !== null}
        title="Reanalyze existing PDFs?"
        closeable={!busy}
        onClose={() => {
          if (!busy) setOptions(null)
        }}
      >
        <div className="stack">
          <p>
            There are no new PDFs. Select the unused PDFs
            whose existing chapters you want to replace.
            Tasks belonging to those replaced chapters
            will also be removed.
          </p>

          {options?.rebuildable_documents.map((item) => (
            <label key={item.id}>
              <input
                type="checkbox"
                checked={selected.includes(item.id)}
                disabled={busy}
                onChange={(event) => {
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, item.id]
                      : current.filter(
                          (id) => id !== item.id,
                        ),
                  )
                }}
              />
              {' '}
              {item.filename}
            </label>
          ))}

          {Boolean(options?.blocked_documents.length) && (
            <p className="muted small">
              {options?.blocked_documents.length} other
              PDF(s) are unavailable for rebuilding.
            </p>
          )}

          <div className="actions">
            <button
              className="button"
              disabled={busy || !selected.length}
              onClick={() => {
                if (options) {
                  void execute(options, selected, true)
                }
              }}
            >
              Replace selected chapters
            </button>

            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setOptions(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      </Modal>
    </section>
  )
}
