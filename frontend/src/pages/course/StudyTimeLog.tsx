import { useState } from 'react'
import type { FormEvent } from 'react'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'
import { logStudyTime } from './scheduleActions'
import type { Task } from './types'

export default function StudyTimeLog({ courseId, task }: { courseId: number; task: Task }) {
  const { loadPlan } = useStudy()
  const [editing, setEditing] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedMinutes, setSavedMinutes] = useState<number>()
  const [error, setError] = useState('')
  const minutes = savedMinutes ?? task.study_time?.minutes

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const saved = await logStudyTime(courseId, task.id, Number(input))
      setSavedMinutes(saved.minutes)
      setEditing(false)
      await loadPlan(courseId)
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="study-time-log">
      {editing ? <form onSubmit={event => void save(event)}>
        <label>Actual time (min)
          <input type="number" required min={1} max={43200} step={1} value={input} onChange={event => setInput(event.target.value)} />
        </label>
        <button className="button small" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        <button className="button small secondary" type="button" onClick={() => { setEditing(false); setError('') }} disabled={busy}>Cancel</button>
      </form> : <>
        {minutes !== undefined && <span className="muted small" aria-live="polite">{minutes} min logged</span>}
        <button className="text-button" type="button" onClick={() => {
          setInput(minutes === undefined ? '' : String(minutes))
          setEditing(true)
        }}>{minutes === undefined ? 'Log study time' : 'Edit study time'}</button>
      </>}
      {error && <p className="small" role="alert">{error}</p>}
    </div>
  )
}
