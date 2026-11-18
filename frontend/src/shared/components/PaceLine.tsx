import {
  addDays,
  dateKey,
  daysBetween,
  percent,
  prettyDate,
} from '../format'

import type {
  CourseConfig,
  StudyPlan,
  Task,
} from '../../pages/course/types'

export function taskTotals(tasks: Task[]) {
  const total = tasks.length

  const done = tasks.filter(
    (task) => task.status === 'Completed',
  ).length

  return {
    total,
    done,
    remaining: total - done,
    progress: percent(done, total),
  }
}

export function ProgressTrack({
  label,
  done,
  total,
  unavailable = false,
}: {
  label: string
  done: number
  total: number
  unavailable?: boolean
}) {
  const progress = percent(done, total)

  return (
    <div className="progress-track">
      <div>
        <span>{label}</span>

        <strong>
          {unavailable ? '—' : `${progress}%`}
        </strong>
      </div>

      {unavailable ? (
        <p className="muted small">
          No study plan yet.
        </p>
      ) : (
        <>
          <div
            className="progress-rail"
            role="progressbar"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
          >
            <span
              style={{
                width: `${progress}%`,
              }}
            />
          </div>

          <small className="muted">
            {done} of {total} tasks completed
          </small>
        </>
      )}
    </div>
  )
}

export default function PaceLine({
  plan,
  config,
  compact = false,
}: {
  plan: StudyPlan
  config: CourseConfig
  compact?: boolean
}) {
  const target =
    plan.end ||
    addDays(
      config.deadline,
      -config.earlyDays,
    )

  const axisEnd =
    plan.end && config.deadline > plan.end
      ? config.deadline
      : plan.end || config.deadline

  const forecast =
    plan.tasks
      .map((task) => task.date)
      .sort()
      .at(-1) || plan.start

  const span = Math.max(
    1,
    daysBetween(
      plan.start,
      axisEnd,
    ),
  )

  const position = (date: string) =>
    Math.min(
      100,
      Math.max(
        0,
        (daysBetween(plan.start, date) /
          span) *
          100,
      ),
    )

  const late = forecast > target

  return (
    <section
      className={
        `pace-line ${compact ? 'compact' : ''}`
      }
      aria-label="Schedule outlook"
    >
      <div className="pace-heading">
        <span
          className={
            `badge ${late ? 'warning' : ''}`
          }
        >
          {late
            ? 'Needs attention'
            : 'On schedule'}
        </span>

        <small>
          Finish {config.earlyDays} days early
        </small>
      </div>

      <p className="pace-summary">
        Planned finish{' '}
        <strong>
          {prettyDate(forecast)}
        </strong>
      </p>

      <div className="pace-axis">
        <span
          className="pace-elapsed"
          style={{
            width:
              `${position(dateKey())}%`,
          }}
        />

        <span
          className="pace-today"
          style={{
            left:
              `${position(dateKey())}%`,
          }}
          title="Today"
        />

        <span
          className="pace-target"
          style={{
            left: `${position(target)}%`,
          }}
          title={
            `Target: ${prettyDate(target)}`
          }
        />

        <span
          className="pace-deadline"
          title={
            `Deadline: ` +
            prettyDate(config.deadline)
          }
        />
      </div>

      <div className="pace-labels">
        <span>
          {prettyDate(plan.start)}
        </span>

        <span>
          {plan.end
            ? `Ends ${prettyDate(plan.end)}`
            : `Target ${prettyDate(target)}`}
        </span>

        <span>
          {plan.end && plan.end !== config.deadline
            ? `Course due ${prettyDate(config.deadline)}`
            : `Due ${prettyDate(config.deadline)}`}
        </span>
      </div>

      {!compact && (
        <p className="muted small">
          {plan.end
            ? 'Tasks are placed on dates from the plan start through the plan end.'
            : 'Tasks are placed on dates through your target.'}
        </p>
      )}
    </section>
  )
}