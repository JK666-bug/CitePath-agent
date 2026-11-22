import { LoaderCircle } from 'lucide-react'

import { Link } from '../../shared/router'

import {
  Modal,
  Notice,
} from '../../shared/components/UI'

export default function AnalysisDialog({
  open,
  busy,
  status,
  error,
  demo,
  courseId,
  onClose,
  onSchedule,
}: {
  open: boolean
  busy: boolean
  status: string
  error: string
  demo: boolean
  courseId: string
  onClose: () => void
  onSchedule?: () => void
}) {
  const title = busy
    ? 'Preparing your course'
    : error
      ? 'Action required'
      : demo
        ? 'Sample schedule updated'
        : 'Course saved'

  const canSetSchedule = !busy && !error && !demo && Boolean(onSchedule)

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      closeable={!busy}
    >
      <div className="stack">
        {busy && (
          <LoaderCircle
            className="spin"
            size={26}
          />
        )}

        <p aria-live="polite">
          {status}
        </p>

        {error && (
          <Notice tone="error">
            {error}
          </Notice>
        )}

        {!busy && (
          <div className="actions">
            {canSetSchedule && (
              <button
                type="button"
                className="button"
                onClick={onSchedule}
              >
                Set daily schedule
              </button>
            )}
            {demo ? (
              <Link
                className="button"
                href="/calendar?course=demo"
              >
                View sample calendar
              </Link>
            ) : (
              courseId && (
                <Link
                  className={canSetSchedule ? 'button secondary' : 'button'}
                  href={`/courses/${courseId}/plan`}
                >
                  View chapters
                </Link>
              )
            )}

            {!canSetSchedule && (
              <button
                type="button"
                className="button secondary"
                onClick={onClose}
              >
                {error ? 'Back to form' : 'Close'}
              </button>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
