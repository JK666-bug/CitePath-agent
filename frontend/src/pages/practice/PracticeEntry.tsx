import type { ChapterPracticeProgress } from '../course/types'
import { Link } from '../../shared/router'

import './practice.css'

export function PracticeEntry({
  courseId,
  progress,
  onStart,
  className = 'button small',
  compact = false,
}: {
  courseId: string | number
  progress?: ChapterPracticeProgress
  onStart: () => void
  className?: string
  compact?: boolean
}) {
  if (progress?.open_session_id != null) {
    return (
      <Link className={className} href={`/practice/${courseId}/sessions/${progress.open_session_id}`}>
        {compact ? 'Continue' : 'Continue practice'}
      </Link>
    )
  }

  return (
    <button type="button" className={className} onClick={onStart}>
      {progress?.has_finished ? 'Practice again' : 'Practice'}
    </button>
  )
}

export function PracticeMastery({ progress }: { progress?: ChapterPracticeProgress }) {
  if (progress?.open_session_id == null || !progress.total) return null

  return (
    <p className="practice-resume-progress">
      <progress aria-label="Concepts mastered" value={progress.mastered} max={progress.total} />
      <span>{progress.mastered} of {progress.total} concepts mastered</span>
    </p>
  )
}
