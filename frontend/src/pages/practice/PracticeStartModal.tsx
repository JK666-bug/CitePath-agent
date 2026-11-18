import { useEffect, useState } from 'react'

import { navigate } from '../../shared/router'
import { messageOf } from '../../shared/request'
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

import { PassThreshold } from './RoundSummary'

type Mode = 'choose' | 'custom'

export default function PracticeStartModal({
  open,
  courseId,
  chapterId,
  onClose,
  initialThreshold = 0.8,
}: {
  open: boolean
  courseId: number
  chapterId: number | null
  onClose: () => void
  initialThreshold?: number
}) {
  const [mode, setMode] = useState<Mode>('choose')
  const [prefs, setPrefs] = useState<PracticePrefsDraft>(emptyPracticePrefs())
  const [passingThreshold, setPassingThreshold] = useState(initialThreshold)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) {
      setPassingThreshold(initialThreshold)
      setMode('choose')
      setPrefs(emptyPracticePrefs())
      setBusy(false)
      setError('')
    }
  }, [open, initialThreshold])

  async function start(nextPrefs: PracticePrefs | null) {
    if (chapterId == null || busy) return
    setBusy(true)
    setError('')
    try {
      const created = await createPractice(courseId, chapterId, { passingThreshold, prefs: nextPrefs })
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
        <PassThreshold value={passingThreshold} onChange={setPassingThreshold} disabled={busy} />
        {mode === 'choose' ? (
          <>
            <p className="muted">
              Each session has at most two rounds with the same pass mark. Custom practice lets you guide difficulty and exam-case style.
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
                {busy ? 'Opening…' : 'Default chapter practice'}
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
