import { useState } from 'react'
import { X } from 'lucide-react'
import type { CalendarTask } from '../course/types'

import { parseDate } from '../../shared/format'
import { messageOf } from '../../shared/request'
import { createPractice } from '../practice/api'

import {
  Link,
  navigate,
} from '../../shared/router'
import {
  Notice,
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
  const [startingId, setStartingId] = useState('')
  const [errorTaskId, setErrorTaskId] = useState('')
  const [error, setError] = useState('')
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
          onClick={onClose}
          aria-label="Close day overview"
        >
          <X size={16} />
        </button>
      </header>

      <p className="muted small">
        {tasks.length}{' '}
        {tasks.length === 1
          ? 'task'
          : 'tasks'}
      </p>

      {!tasks.length && (
        <p className="day-empty muted">
          Nothing scheduled. A little
          breathing room for your day.
        </p>
      )}

      <div className="day-task-list">
        {tasks.map((task) => (
          <article
            key={`${task.courseId}-${task.id}`}
            className="day-task"
          >
            <div className="actions spread">
              <span className="badge">
                {task.kind}
              </span>
            </div>

            <h3>{task.title}</h3>

            <p className="muted small">
              {task.courseName}
            </p>

            <Sources
              sources={task.sources}
            />

            <p className="small muted">
              {task.status}
            </p>

            <div className="actions">
              {error && errorTaskId === task.id && task.kind === 'Practice' && (
                <Notice tone="error">{error}</Notice>
              )}
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
                    disabled={startingId === task.id}
                    onClick={() => {
                      setError('')
                      setErrorTaskId(task.id)
                      setStartingId(task.id)
                      void createPractice(
                        Number(task.courseId),
                        Number(task.chapterId),
                      )
                        .then((created) =>
                          navigate(
                            `/practice/${task.courseId}/sessions/${created.id}`,
                          ),
                        )
                        .catch((reason) => {
                          setError(messageOf(reason))
                          setStartingId('')
                        })
                    }}
                  >
                    {startingId === task.id
                      ? 'Writing question…'
                      : 'Start practice'}
                  </button>
                )
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
    </aside>
  )
}