import { useState } from 'react'
import type { StudyPlan } from './types'
import { getPlanVersion, getPlanVersions } from './api'
import type { PlanSnapshot, PlanVersion } from './api'
import { messageOf } from '../../shared/request'
import { Modal, Notice, Sources } from '../../shared/components/UI'
import { prettyDate } from '../../shared/format'

const assumptionLabels: Record<string, string> = {
  goal: 'a general understanding of the course as the learning goal',
  prior_knowledge: 'prior knowledge was not specified',
  daily_minutes: 'a default daily study budget',
  reading_words_per_minute: 'a default reading pace',
}

export function EstimatedWorkload({ plan }: { plan: StudyPlan }) {
  const remaining = plan.tasks.filter((task) => task.status !== 'Completed')
  const known = remaining.filter((task) => typeof task.estimated_minutes === 'number')
  const total = known.reduce((sum, task) => sum + (task.estimated_minutes ?? 0), 0)
  const daily = new Map<string, { minutes: number; unknown: boolean }>()
  for (const task of remaining) {
    const day = daily.get(task.date) ?? { minutes: 0, unknown: false }
    if (typeof task.estimated_minutes === 'number') day.minutes += task.estimated_minutes
    else day.unknown = true
    daily.set(task.date, day)
  }
  const budget = plan.planning_profile?.daily_minutes
  const assumptions = plan.planning_profile?.assumptions ?? []
  if (typeof plan.estimated_total_minutes !== 'number' && !known.length) return null
  return (
    <section className="panel stack plan-estimates">
      <h2>Estimated study time</h2>
      <div className="plan-stats">
        <div><small>Whole plan estimate</small><strong>{plan.estimated_total_minutes ?? '—'} min</strong></div>
        <div><small>Remaining estimate</small><strong>{known.length < remaining.length ? 'At least ' : ''}{total} min</strong></div>
        {typeof budget === 'number' && <div><small>Your daily study budget</small><strong>{budget} min</strong></div>}
      </div>
      <p className="muted small">{plan.estimate_basis || 'Planning estimates depend on the lecture material and your selected study pace.'} Actual time may vary.</p>
      {plan.capacity?.over_capacity && <Notice>Estimated remaining work exceeds the time available in your study window. Extend the dates or revise your daily study budget.</Notice>}
      {assumptions.length > 0 && <p className="muted small">Planning assumptions: {assumptions.map((assumption) => assumptionLabels[assumption] ?? assumption).join('; ')}. Adjust your study profile below if needed.</p>}
      {daily.size > 0 && (
        <div className="daily-workload" aria-label="Estimated daily workload">
          {[...daily.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, day]) => (
            <div key={date} className="daily-workload-row">
              <span>{prettyDate(date)}</span>
              <span>{day.unknown ? 'At least ' : ''}{day.minutes} estimated min</span>
              {typeof budget === 'number' && day.minutes > budget && <span className="badge">Over your daily budget</span>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

export function PlanHistory({ courseId, currentVersion }: { courseId: number; currentVersion: number }) {
  const [open, setOpen] = useState(false)
  const [versions, setVersions] = useState<PlanVersion[]>([])
  const [snapshot, setSnapshot] = useState<PlanSnapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function showHistory() {
    setOpen(true)
    setSnapshot(null)
    setVersions([])
    setBusy(true)
    setError('')
    try { setVersions((await getPlanVersions(courseId)).versions) }
    catch (reason) { setError(messageOf(reason)) }
    finally { setBusy(false) }
  }
  async function showVersion(version: number) {
    setBusy(true)
    setError('')
    try { setSnapshot(await getPlanVersion(courseId, version)) }
    catch (reason) { setError(messageOf(reason)) }
    finally { setBusy(false) }
  }
  return (
    <>
      <button type="button" className="button small secondary" onClick={() => void showHistory()}>Version history</button>
      <Modal open={open} title="Plan version history" onClose={() => setOpen(false)}>
        <div className="stack">
          <p>Saved schedules are read-only. Your current plan remains version {currentVersion}.</p>
          {busy && <p role="status">Loading saved plan…</p>}
          {error && <Notice tone="error">{error}{!snapshot && !versions.length && <button className="text-button" onClick={() => void showHistory()}>Retry version history</button>}</Notice>}
          {snapshot ? (
            <>
              <button type="button" className="text-button" disabled={busy} onClick={() => setSnapshot(null)}>Back to saved versions</button>
              <h3>Saved plan v{snapshot.version}</h3>
              <p className="muted small">{snapshot.saved_at} · {snapshot.change_type.replaceAll('_', ' ')}</p>
              <p>{snapshot.plan.reason}</p>
              <p className="muted small">This snapshot contains {snapshot.plan.chapters.length} chapters and {snapshot.plan.tasks.filter((task) => task.status === 'Completed').length} completed tasks.</p>
              {snapshot.plan.chapters.map((chapter) => (
                <section className="stack saved-plan-chapter" key={chapter.id}>
                  <h4>{chapter.title}</h4>
                  <Sources sources={chapter.sources} courseId={courseId} />
                  {snapshot.plan.tasks.filter((task) => task.chapterId === chapter.id).map((task) => (
                    <p className="small" key={task.id}>{task.title} · {prettyDate(task.date)} · {task.status}{typeof task.estimated_minutes === 'number' ? ` · ${task.estimated_minutes} estimated min` : ''}</p>
                  ))}
                </section>
              ))}
            </>
          ) : !busy && (
            versions.length ? versions.map((version) => (
              <article className="plan-history-row" key={version.version}>
                <div><strong>Version {version.version}</strong><p className="muted small">{version.created_at} · {version.change_type.replaceAll('_', ' ')}</p><p className="small">{version.reason}</p></div>
                <button className="button small secondary" type="button" onClick={() => void showVersion(version.version)}>View version {version.version}</button>
              </article>
            )) : !error && <p>No earlier plan snapshots have been saved yet.</p>
          )}
        </div>
      </Modal>
    </>
  )
}
