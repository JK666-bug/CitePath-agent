import { useState } from 'react'
import { X } from 'lucide-react'
import type { CalendarTask } from '../course/types'

import { parseDate } from '../../shared/format'
import PracticeStartModal from '../practice/PracticeStartModal'

import {
  Link,
} from '../../shared/router'
import {
  Sources,
} from '../../shared/components/UI'

export default function DayOverview({
  date,
  tasks,
  onClose,
  onComplete,
}: {
  date: string
  tasks: CalendarTask[]
  onClose: () => void
  onComplete: (task: CalendarTask) => void
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
        {tasks.map((task) => (
          <article key={task.id} className="panel">
            <p className="eyebrow">
              {task.courseName}
            </p>
            <h3>{task.title}</h3>
            <Sources sources={task.sources} />
            <p className="small muted">
              {task.status}
            </p>

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
                  <button
                    className="button small"
                    onClick={() =>
                      setPracticeTarget({
                        courseId: Number(task.courseId),
                        chapterId: Number(task.chapterId),
                      })
                    }
                  >
                    Start practice
                  </button>
                )
              ) : task.kind === 'Reading' && task.courseId !== 'demo' ? (
                <Link
                  className="button small"
                  href={
                    `/courses/${task.courseId}/read?task=` +
                    encodeURIComponent(task.id)
                  }
                >
                  Open reading
                </Link>
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
