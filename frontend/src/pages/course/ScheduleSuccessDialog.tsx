import { Modal } from '../../shared/components/UI'
import { Link } from '../../shared/router'
import { prettyDate } from '../../shared/format'

import './schedulePanel.css'

export type ScheduleStep = {
  step: number
  tool: string
  ok: boolean
  arguments?: Record<string, unknown>
  observation: unknown
  source?: 'model' | 'rules' | 'system'
}

type ScheduleSlot = { date: string; minutes: number | null }

export type ScheduleSummary = {
  strategy: string
  strategy_source: 'model' | 'rules' | 'system' | 'preference'
  reason: string
  first_date: string
  completed_preserved: number
  changes: { task_id: string; title: string; before: ScheduleSlot[]; after: ScheduleSlot[] }[]
}

export type SavedSchedule = {
  method: 'agent' | 'baseline'
  start: string
  steps: ScheduleStep[]
  summary?: ScheduleSummary
}

const stepLabels: Record<string, string> = {
  check_study_capacity: 'Check that your available study time covers the remaining tasks',
  get_planning_snapshot: 'Check your chapters and remaining tasks',
  get_learning_report: 'Review recent practice and exam results',
  estimate_task_time: 'Estimate how long each task will take',
  propose_daily_schedule: 'Arrange tasks on your available study days',
  validate_daily_schedule: 'Check dates, daily study time, and task coverage',
  save_schedule: 'Save the schedule and keep completed work',
  request_clarification: 'Double-check your available study days',
}

const orderLabels: Record<string, string> = {
  new_first: 'Reading first',
  weak_first: 'Weak chapters first',
  chapter_order: 'Chapter order',
}

const strategySources: Record<ScheduleSummary['strategy_source'], string> = {
  model: 'Chosen by the AI planner',
  rules: 'Chosen by fixed rules',
  system: 'Chosen during validation',
  preference: 'Your selected order',
}

function formatSlots(slots: ScheduleSlot[]) {
  return slots.map(slot => {
    const date = prettyDate(slot.date)
    return slot.minutes == null ? date : `${date} (${slot.minutes} min)`
  }).join(', ')
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === 'object') return value as Record<string, unknown>
}

function getPublishedProposal(steps: ScheduleStep[]) {
  const saved = steps.findLast(step =>
    step.tool === 'save_schedule' && step.ok && asRecord(step.observation)?.status === 'saved',
  )
  const candidateId = saved?.arguments?.candidate_id
  if (candidateId === undefined) return undefined

  return steps
    .filter(step => step.tool === 'propose_daily_schedule' && step.ok)
    .map(step => asRecord(step.observation))
    .find(proposal => proposal?.candidate_id === candidateId)
}

function firstStudyDate(proposal: Record<string, unknown> | undefined, start: string) {
  if (!Array.isArray(proposal?.slots)) return start

  let earliest = ''
  for (const slot of proposal.slots) {
    const date = asRecord(slot)?.date
    if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) && (!earliest || date < earliest)) {
      earliest = date
    }
  }
  return earliest || start
}

export default function ScheduleSuccessDialog({ courseId, schedule, onClose }: {
  courseId: number
  schedule: SavedSchedule | null
  onClose: () => void
}) {
  const steps = schedule?.steps.filter(step => Object.hasOwn(stepLabels, step.tool)) ?? []
  const proposal = getPublishedProposal(steps)
  const summary = schedule?.summary
  const strategy = summary?.strategy ?? (typeof proposal?.strategy === 'string' ? proposal.strategy : '')
  const order = orderLabels[strategy]
  const date = schedule ? summary?.first_date || firstStudyDate(proposal, schedule.start) : ''
  const newCount = summary?.changes.filter(change => !change.before.length).length ?? 0
  const updatedCount = (summary?.changes.length ?? 0) - newCount
  const changeLabel = [
    newCount ? `${newCount} newly scheduled` : '',
    updatedCount ? `${updatedCount} updated` : '',
  ].filter(Boolean).join(' · ')
  const calendarQuery = new URLSearchParams({ course: String(courseId) })
  if (date) calendarQuery.set('date', date)

  return (
    <Modal open={Boolean(schedule)} title="Your daily plan is ready" onClose={onClose}>
      {schedule && (
        <div className="schedule-success">
          {summary ? <div className="schedule-decision">
            <strong>{order}</strong>
            <span className="muted small">{strategySources[summary.strategy_source]}</span>
            <p>{summary.reason}</p>
          </div> : <p>Your schedule is saved and available on the calendar.</p>}

          {summary && (
            summary.changes.length ? (
              <details className="schedule-success-steps">
                <summary>Schedule changes · {changeLabel}</summary>
                <ul className="schedule-change-list">
                  {summary.changes.map(change => (
                    <li key={change.task_id}>
                      <strong>{change.title}</strong>
                      {change.before.length > 0 && <span><b>Previously</b> {formatSlots(change.before)}</span>}
                      <span><b>{change.before.length ? 'Now' : 'Scheduled'}</b> {formatSlots(change.after)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : <p className="muted small">This plan uses the same dates and study times as before.</p>
          )}
          {Boolean(summary?.completed_preserved) && (
            <p className="muted small">{summary?.completed_preserved} completed {summary?.completed_preserved === 1 ? 'task kept' : 'tasks kept'}.</p>
          )}

          <details className="schedule-success-steps">
            <summary>How your plan was made</summary>
            <p className="muted small">
              {schedule.method === 'agent' ? 'AI planner' : 'Fixed rules'}{order && !summary ? ` · ${order}` : ''}
            </p>
            {steps.length > 0 && (
              <ol>
                {steps.map(step => {
                  const needsChange = step.tool === 'validate_daily_schedule' && asRecord(step.observation)?.valid === false
                  return (
                    <li key={step.step}>
                      {stepLabels[step.tool]}
                      {summary && step.source === 'system' && step.tool === 'save_schedule' && schedule.method === 'agent' && <span className="muted small"> · Saved after system validation</span>}
                      {(!step.ok || needsChange) && <small>{step.ok ? 'Needed changes' : 'Could not complete'}</small>}
                    </li>
                  )
                })}
              </ol>
            )}
          </details>

          <div className="actions">
            <Link className="button" href={`/calendar?${calendarQuery}`}>View calendar</Link>
            <Link className="button secondary" href={`/courses/${courseId}/plan`}>View course plan</Link>
          </div>
        </div>
      )}
    </Modal>
  )
}
