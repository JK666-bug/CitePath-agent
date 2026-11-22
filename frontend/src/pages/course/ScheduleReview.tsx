import { useEffect, useRef, useState } from 'react'
import { ApiError, messageOf } from '../../shared/request'
import { Link } from '../../shared/router'
import { Loading, Modal, Notice } from '../../shared/components/UI'
import { useStudy } from '../../shared/StudyProvider'
import ScheduleSuccessDialog from './ScheduleSuccessDialog'
import { applySchedule, previewSchedule, scheduleForDialog } from './scheduleActions'

export default function ScheduleReview({ courseId, onClose }: { courseId: number; onClose: () => void }) {
  const { loadPlan, refreshCourses } = useStudy()
  const [result, setResult] = useState<Awaited<ReturnType<typeof previewSchedule>> | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [applying, setApplying] = useState(false)
  const request = useRef<ReturnType<typeof previewSchedule> | null>(null)
  const settings = `/courses/${courseId}/info?edit=schedule`

  useEffect(() => {
    let active = true
    request.current ??= previewSchedule(courseId, crypto.randomUUID())
    void request.current.then(response => {
      if (!active) return
      if (response.status === 'preview') setResult(response)
      else setError(response.message)
    }).catch(reason => {
      if (active) setError(messageOf(reason))
    })
    return () => { active = false }
  }, [courseId, attempt])

  async function apply() {
    if (applying || !result || result.unchanged) return
    setApplying(true)
    setError('')
    try {
      const saved = await applySchedule(courseId, result.run_id)
      await Promise.allSettled([loadPlan(courseId), refreshCourses()])
      setResult(saved)
    } catch (reason) {
      if (reason instanceof ApiError && (reason.status === 0 || reason.status >= 500)) {
        // The request may have succeeded. Retrying the same preview is safe.
        setError('Could not confirm the update. Retry Apply schedule to check the result.')
      } else {
        setResult(null)
        setError(messageOf(reason))
      }
    } finally {
      setApplying(false)
    }
  }

  if (result) {
    return <ScheduleSuccessDialog
      courseId={courseId}
      schedule={scheduleForDialog(result, 'agent')}
      onClose={onClose}
      onApply={result.status === 'preview' && !result.unchanged ? () => void apply() : undefined}
      applying={applying}
      error={error}
    />
  }

  return (
    <Modal open title={error ? 'Schedule needs attention' : 'Preparing schedule preview'} onClose={onClose}>
      {error ? <div className="stack">
        <Notice tone="error">{error}</Notice>
        <div className="actions">
          <Link className="button secondary" href={settings}>Edit study settings</Link>
          <button className="button secondary" type="button" onClick={() => {
            request.current = null
            setError('')
            setAttempt(current => current + 1)
          }}>Try again</button>
        </div>
      </div> : <Loading text="Checking your current progress and study settings…" />}
    </Modal>
  )
}
