import { useEffect, useState } from 'react'
import type { StudyPlan } from './types'
import { request } from '../../shared/request'
import { prettyDate } from '../../shared/format'

export default function PlanHistory({ courseId, version }: { courseId: number; version: number }) {
  const [versions, setVersions] = useState<{ version: number; change_type: string; created_at: string }[]>([])
  const [selected, setSelected] = useState<StudyPlan | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void request<{ versions: typeof versions }>(`/api/courses/${courseId}/plan/versions`)
      .then((value) => { if (active) setVersions(value.versions) })
      .catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [courseId, version])
  return <details className="panel"><summary>Plan history</summary>
    <p className="muted small">Read-only snapshots show learning status at publication time. Your current progress remains separate.</p>
    {error && <p role="alert">{error}</p>}
    <div className="actions">{versions.map((row) => <button className="button small secondary" key={row.version} onClick={() => {
      void request<{ plan: StudyPlan }>(`/api/courses/${courseId}/plan/versions/${row.version}`)
        .then((value) => { setSelected(value.plan); setError('') }).catch((e) => setError(e.message))
    }}>v{row.version} · {row.change_type}</button>)}</div>
    {selected && <div><h3>Version {selected.version}</h3><p>{selected.reason}</p>
      <ul>{selected.tasks.map((task) => <li key={task.id}>{task.title} · {task.date ? prettyDate(task.date) : 'Not scheduled'} · {task.status}</li>)}</ul>
    </div>}
  </details>
}
