import { useState } from 'react'
import type { Task } from './types'

import { prettyDate } from '../../shared/format'
import { messageOf } from '../../shared/request'
import { createPractice } from '../practice/api'

import {
  Link,
  navigate,
} from '../../shared/router'

import {
  Modal,
  Notice,
  Sources,
} from '../../shared/components/UI'

export default function TaskDetails({
  task,
  courseId,
  onClose,
  onComplete,
}: {
  task: Task | null
  courseId: string
  onClose: () => void
  onComplete: (task: Task) => void
}) {
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  return (
    <Modal
      open={Boolean(task)}
      title="Task details"
      onClose={onClose}
    >
      {task && (
        <div className="stack">
          <span className="badge">
            {task.kind}
          </span>

          <h3>{task.title}</h3>

          <p className="muted">
            {prettyDate(task.date, true)}
            {' · '}
            {task.status}
          </p>

          <div>
            <strong>Concepts</strong>

            <p className="muted">
              {task.concepts.join(' · ')}
            </p>
          </div>

          <div>
            <strong>
              Reading source
            </strong>

            <Sources
              sources={task.sources}
            />
          </div>

          {error && <Notice tone="error">{error}</Notice>}

          <div className="actions">
            {task.kind === 'Practice' ? (
              courseId === 'demo' ? (
                <Link
                  className="button"
                  href={
                    `/practice/demo/${task.chapterId}`
                  }
                >
                  Open chapter practice
                </Link>
              ) : (
                <button
                  className="button"
                  disabled={starting}
                  onClick={() => {
                    setError('')
                    setStarting(true)
                    void createPractice(
                      Number(courseId),
                      Number(task.chapterId),
                    )
                      .then((created) =>
                        navigate(
                          `/practice/${courseId}/sessions/${created.id}`,
                        ),
                      )
                      .catch((reason) => {
                        setError(messageOf(reason))
                        setStarting(false)
                      })
                  }}
                >
                  {starting ? 'Writing question…' : 'Start practice'}
                </button>
              )
            ) : task.kind === 'Review' && courseId !== 'demo' ? (
              <Link
                className="button"
                href={
                  `/courses/${courseId}/chapters/${task.chapterId}/reports`
                }
              >
                View reports
              </Link>
            ) : (
              <button
                className="button"
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
          </div>
        </div>
      )}
    </Modal>
  )
}