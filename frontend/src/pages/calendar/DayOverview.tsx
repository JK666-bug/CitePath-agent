import { useState } from 'react'
import { X } from 'lucide-react'
import type { CalendarTask } from '../course/types'

import { parseDate } from '../../shared/format'
import { PracticeEntry, PracticeMastery } from '../practice/PracticeEntry'
import PracticeStartModal from '../practice/PracticeStartModal'

import {
  Link,
} from '../../shared/router'
import SourceSummary from '../course/SourceSummary'

export default function DayOverview({
  date,
  tasks,
  onClose,
  onComplete,
  events,
}: {
  date: string
  tasks: CalendarTask[]
  onClose: () => void
  onComplete: (task: CalendarTask) => void
  events: { date: string; title: string; courseName: string }[]
}) {
  const [practiceTarget, setPracticeTarget] = useState<{
    courseId: number
    chapterId: number
  } | null>(null)

  return (
    <aside
      className="day-overview"
      aria-label="Selected day overview"
    >
      <header>
        <div>
          <p className="eyebrow">
            Day overview
          </p>

          <h2>
            {new Intl.DateTimeFormat(
              'en-US',
              {
                weekday: 'long',
                month: 'short',
                day: 'numeric',
              },
            ).format(parseDate(date))}
          </h2>
        </div>

        <button
          className="icon-button"
          aria-label="Close day overview"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </header>

      <div className="stack">
        {events.map((event, i) => <article className="panel" key={`event-${i}`}><p className="eyebrow">{event.courseName} · Important date</p><h3>{event.title}</h3></article>)}
        {tasks.map((task) => (
          <article key={task.id} className="panel">
            <p className="eyebrow">
              {task.courseName}
            </p>
            <p className={`calendar-kind kind-${task.kind.toLowerCase()}`}>{task.kind === 'Reading' ? 'Read' : task.kind}</p>
            <h3>{task.title}</h3>
            <SourceSummary sources={task.sources} />
            <p className="small muted">
              {task.status}
              {task.minutes ? ` · ${task.minutes} min today` : ''}
            </p>
            {task.kind === 'Practice' && <PracticeMastery progress={task.practice_progress} />}

            <div className="actions">
              {task.kind === 'Practice' ? (
                task.courseId === 'demo' ? (
                  <Link
                    className="button small"
                    href={
                      `/practice/demo/${task.chapterId}`
                    }
                  >
                    Open practice
                  </Link>
                ) : (
                  <PracticeEntry
                    courseId={task.courseId}
                    progress={task.practice_progress}
                    onStart={() => setPracticeTarget({
                      courseId: Number(task.courseId),
                      chapterId: Number(task.chapterId),
                    })}
                  />
                )
              ) : task.kind === 'Reading' && task.courseId !== 'demo' ? (
                <>
                  <Link
                    className="button small"
                    href={
                      `/courses/${task.courseId}/read?task=` +
                      encodeURIComponent(task.id)
                    }
                  >
                    Open reading
                  </Link>
                  <button
                    className="button small secondary"
                    disabled={task.status === 'Completed'}
                    onClick={() => onComplete(task)}
                  >
                    {task.status === 'Completed'
                      ? 'Completed'
                      : 'Mark done'}
                  </button>
                </>
              ) : task.kind === 'Review' && task.courseId !== 'demo' ? (
                <Link
                  className="button small"
                  href={
                    `/courses/${task.courseId}/chapters/${task.chapterId}/reports`
                  }
                >
                  View reports
                </Link>
              ) : (
                <button
                  className="button small secondary"
                  disabled={
                    task.status ===
                    'Completed'
                  }
                  onClick={() =>
                    onComplete(task)
                  }
                >
                  {task.status === 'Completed'
                    ? 'Completed'
                    : 'Mark complete'}
                </button>
              )}

              <Link
                className="small"
                href={
                  `/courses/${task.courseId}/plan?task=` +
                  encodeURIComponent(
                    task.id,
                  )
                }
              >
                View in plan
              </Link>
            </div>
          </article>
        ))}
      </div>

      <PracticeStartModal
        open={practiceTarget != null}
        courseId={practiceTarget?.courseId ?? 0}
        chapterId={practiceTarget?.chapterId ?? null}
        onClose={() => setPracticeTarget(null)}
      />
    </aside>
  )
}
