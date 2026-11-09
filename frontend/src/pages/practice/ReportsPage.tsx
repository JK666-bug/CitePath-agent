import { useEffect, useState } from 'react'

import { Link } from '../../shared/router'
import { messageOf } from '../../shared/request'
import {
  Empty,
  Loading,
  PageHeader,
} from '../../shared/components/UI'

import { listReports } from './api'
import type { ChapterReports } from './api'

import './practice.css'

export default function ReportsPage({
  courseId,
  chapterId,
}: {
  courseId: string
  chapterId: string
}) {
  const [reports, setReports] =
    useState<ChapterReports | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    listReports(Number(courseId), Number(chapterId))
      .then((result) => {
        if (active) setReports(result)
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [chapterId, courseId])

  if (error && !reports) {
    return (
      <Empty title="Reports unavailable">
        <p>{error}</p>
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </Empty>
    )
  }

  if (!reports) {
    return <Loading text="Loading reports…" />
  }

  const practiceCorrect = reports.practice.reduce(
    (sum, item) => sum + item.correct_count,
    0,
  )
  const practiceWrong = reports.practice.reduce(
    (sum, item) => sum + item.wrong_count,
    0,
  )

  return (
    <div className="practice-session stack">
      <PageHeader
        eyebrow="Review"
        title={reports.chapter_title}
        subtitle="Finished practice rounds and every exam for this chapter."
      />

      <section className="stack">
        <h2>Practice</h2>
        {reports.practice.length > 0 && (
          <p className="muted">
            {reports.practice.length} finished
            {reports.practice.length === 1 ? ' round' : ' rounds'}.
            {' '}
            {practiceCorrect} correct. {practiceWrong} wrong.
          </p>
        )}
        {!reports.practice.length && (
          <p className="muted">No finished practice yet.</p>
        )}
        {reports.practice.map((item, index) => (
          <article className="panel" key={item.id}>
            <div className="actions spread">
              <p className="question-concept">
                Round {reports.practice.length - index}
              </p>
              <span className="badge">
                {item.correct_count} correct · {item.wrong_count} wrong
              </span>
            </div>
            <p className="muted">
              {item.started_at} to {item.finished_at}
            </p>
            <Link
              href={`/practice/${courseId}/sessions/${item.id}`}
            >
              View practice report
            </Link>
          </article>
        ))}
      </section>

      <section className="stack">
        <h2>Exams</h2>
        {!reports.exams.length && (
          <p className="muted">No finished exams yet.</p>
        )}
        {reports.exams.map((item) => (
          <article className="panel" key={item.id}>
            <div className="actions spread">
              <p className="question-concept">
                {item.score === null ? 'Exam' : `${item.score}%`}
              </p>
              <span className="badge">
                {item.passed ? 'Passed' : 'Not passed'}
              </span>
            </div>
            <p className="muted">
              {item.finished_at}
              {' · '}
              {item.correct_count} of {item.total} correct
              {' · '}
              {item.wrong_count} wrong
            </p>
            <Link href={`/exams/${courseId}/${item.id}/report`}>
              View exam report
            </Link>
          </article>
        ))}
      </section>

      <Link href={`/courses/${courseId}/plan`}>
        Back to plan
      </Link>
    </div>
  )
}
