import { useState } from 'react'
import type { Task } from './types'

import { prettyDate } from '../../shared/format'
import PracticeStartModal from '../practice/PracticeStartModal'

import {
  Link,
} from '../../shared/router'

import {
  Modal,
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
  const [practiceOpen, setPracticeOpen] = useState(false)
  const numericId = Number(courseId)

  return (
    <>
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
                    onClick={() => setPracticeOpen(true)}
                  >
                    Start practice
                  </button>
                )
              ) : task.kind === 'Reading' && courseId !== 'demo' ? (
                <Link
                  className="button"
                  href={
                    `/courses/${courseId}/read?task=` +
                    encodeURIComponent(task.id)
                  }
                >
                  Open reading
                </Link>
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
                  onClick={() => onComplete(task)}
                >
                  Mark complete
                </button>
              )}
            </div>
          </div>
        )}
      </Modal>

      {courseId !== 'demo' && task?.kind === 'Practice' && (
        <PracticeStartModal
          open={practiceOpen}
          courseId={numericId}
          chapterId={Number(task.chapterId)}
          onClose={() => setPracticeOpen(false)}
        />
      )}
    </>
  )
}
