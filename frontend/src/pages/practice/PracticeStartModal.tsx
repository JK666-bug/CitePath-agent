import { useEffect, useState } from 'react'

import { navigate } from '../../shared/router'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'
import {
  Modal,
  Notice,
} from '../../shared/components/UI'

import { createPractice, type PracticePrefs } from './api'
import {
  emptyPracticePrefs,
  PracticePrefsFields,
  toPracticePrefs,
  type PracticePrefsDraft,
} from './PracticePrefsPanel'

type Mode = 'choose' | 'custom'

export default function PracticeStartModal({
  open,
  courseId,
  chapterId,
  onClose,
}: {
  open: boolean
  courseId: number
  chapterId: number | null
  onClose: () => void
}) {
  const { loadPlan } = useStudy()
  const [mode, setMode] = useState<Mode>('choose')
  const [prefs, setPrefs] = useState<PracticePrefsDraft>(emptyPracticePrefs())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) {
      setMode('choose')
      setPrefs(emptyPracticePrefs())
      setBusy(false)
      setError('')
    }
  }, [open])

  async function start(nextPrefs: PracticePrefs | null) {
    if (chapterId == null || busy) return
    setBusy(true)
    setError('')
    try {
      const created = await createPractice(courseId, chapterId, nextPrefs)
      await loadPlan(courseId)
      onClose()
      navigate(`/practice/${courseId}/sessions/${created.id}`)
    } catch (reason) {
      setError(messageOf(reason))
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title="Start practice"
      closeable={!busy}
      onClose={onClose}
    >
      <div className="stack">
        {mode === 'choose' ? (
          <>
            <p className="muted">
              Default keeps the usual mastery path. Custom lets you guide
              difficulty and exam-case style.
            </p>
            {error && <Notice tone="error">{error}</Notice>}
            <div className="actions">
              <button
                className="button"
                disabled={busy || chapterId == null}
                onClick={() => {
                  void start(null)
                }}
              >
                {busy ? 'Opening…' : 'Default mastery practice'}
              </button>
              <button
                className="button secondary"
                disabled={busy || chapterId == null}
                onClick={() => {
                  setError('')
                  setMode('custom')
                }}
              >
                Custom practice
              </button>
            </div>
          </>
        ) : (
          <>
            <PracticePrefsFields
              courseId={courseId}
              value={prefs}
              onChange={setPrefs}
              active={open && mode === 'custom'}
            />
            {error && <Notice tone="error">{error}</Notice>}
            <div className="actions">
              <button
                className="button"
                disabled={busy}
                onClick={() => {
                  void start(toPracticePrefs(prefs))
                }}
              >
                {busy ? 'Opening…' : 'Start custom practice'}
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => {
                  setError('')
                  setMode('choose')
                }}
              >
                Back
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
