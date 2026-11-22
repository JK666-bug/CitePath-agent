import PaceLine, {
  ProgressTrack,
  taskTotals,
} from '../../shared/components/PaceLine'
import { Link, navigate, useLocation } from '../../shared/router'
import { prettyDate } from '../../shared/format'
import type { CourseDetail, StudyPlan } from './types'
import { decodeBrief } from '../courseEditor/brief'
import ScheduleReview from './ScheduleReview'
import {
  hasUnappliedSettings,
  lastScheduledDate,
  scheduleReviewHref,
  studyDateKey,
} from './scheduleActions'
import type { Workflow } from './scheduleActions'

function planScheduleStats(plan: StudyPlan) {
  const today = studyDateKey()
  let plannedFinish = ''
  let overdue = 0
  let unscheduled = 0
  for (const task of plan.tasks) {
    const date = lastScheduledDate(task)
    if (date > plannedFinish) plannedFinish = date
    if (task.status === 'Completed') continue
    if (!date) unscheduled++
    else if (date < today) overdue++
  }
  return { plannedFinish, overdue, unscheduled, totals: taskTotals(plan.tasks) }
}

export function StudyScheduleAttention({
  courseId,
  course,
  plan,
  onEditSettings,
}: {
  courseId: string
  course: CourseDetail
  plan: StudyPlan
  onEditSettings: () => void
}) {
  const { search } = useLocation()
  const config = decodeBrief(course.student_brief)
  const { overdue, unscheduled, totals } = planScheduleStats(plan)
  const hasScheduleSettings = Boolean(config.deadline && (
    plan.schedule_run_id || config.scheduling_profile || plan.scheduling_profile
  ))
  const settingsHref = `/courses/${courseId}/info?edit=schedule`
  const pendingSettings = hasUnappliedSettings(config, plan)
  const numericId = Number(courseId)

  if (totals.remaining <= 0) return null

  return (
    <>
      <section className="panel plan-schedule-attention" aria-label="Study schedule">
        <div>
          <strong>Study schedule</strong>
          {(overdue > 0 || unscheduled > 0) && <p className="muted small">{[
            overdue > 0 && `${overdue} overdue`,
            unscheduled > 0 && `${unscheduled} not scheduled`,
          ].filter(Boolean).join(' · ')}</p>}
          {pendingSettings && <p className="muted small">Saved settings are waiting to be applied to the calendar.</p>}
        </div>
        {hasScheduleSettings ? (
          <Link className="button small" href={scheduleReviewHref(courseId)}>
            {plan.schedule_run_id ? 'Replan remaining tasks' : 'Review daily plan'}
          </Link>
        ) : (
          <Link className="button small secondary" href={settingsHref}>Set up daily schedule</Link>
        )}
      </section>

      {search.get('review') === 'schedule' && hasScheduleSettings && (
        <ScheduleReview
          courseId={numericId}
          onClose={() => navigate(`/courses/${courseId}/info`, true)}
          onEditSettings={onEditSettings}
        />
      )}
    </>
  )
}

export default function PlanOverview({
  course,
  plan,
  workflow,
}: {
  course: CourseDetail
  plan: StudyPlan
  workflow: Workflow | null
}) {
  const config = decodeBrief(course.student_brief)
  const { plannedFinish, unscheduled, totals } = planScheduleStats(plan)
  const remainingTasks = plan.tasks.filter(task => task.status !== 'Completed')
  const calibratedKinds = (['Reading', 'Practice'] as const).filter(kind =>
    workflow?.study_time_samples?.[kind] && remainingTasks.some(task => task.kind === kind),
  )
  const plannedMinutes = remainingTasks.reduce((total, task) =>
    total + (task.schedule?.reduce((sum, slot) => sum + slot.minutes, 0) ?? task.estimated_minutes ?? 0), 0)
  const difference = (workflow?.estimated_minutes ?? plannedMinutes) - plannedMinutes

  return (
    <div className="course-plan-overview">
      <section className="panel">
        <h2>Your course progress</h2>

        <ProgressTrack
          label="Planned tasks completed"
          done={totals.done}
          total={totals.total}
        />

        <div className="plan-stats">
          <div>
            <small>Tasks</small>
            <strong>
              {totals.done}/{totals.total}
            </strong>
          </div>

          <div>
            <small>Remaining</small>
            <strong>
              {totals.remaining}
            </strong>
          </div>

          <div>
            <small>Planned finish</small>
            <strong>
              {plannedFinish ? prettyDate(plannedFinish) : 'Not scheduled'}
            </strong>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Schedule outlook</h2>

        {plannedFinish ? (
          <PaceLine plan={plan} config={config} />
        ) : (
          <p className="muted">Learning tasks are ready to schedule.</p>
        )}

        {totals.remaining > 0 && workflow && <div className="plan-remaining-time">
          <p><strong>{workflow.estimated_minutes} min</strong> estimated for remaining tasks</p>
          {calibratedKinds.length > 0 && <p className="muted small">
            Based on {calibratedKinds.map(kind => `${workflow.study_time_samples?.[kind]} recent ${kind.toLowerCase()} records`).join(' and ')}.
            {unscheduled === 0 && plannedMinutes > 0 && difference !== 0 &&
              ` ${Math.abs(difference)} min ${difference > 0 ? 'more' : 'less'} than the current schedule.`}
          </p>}
        </div>}
      </section>
    </div>
  )
}
