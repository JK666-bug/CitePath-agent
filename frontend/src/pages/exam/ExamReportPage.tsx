import { useEffect, useState } from 'react'

import {
  Link,
  navigate,
} from '../../shared/router'
import { prettyDate } from '../../shared/format'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'
import {
  Empty,
  Loading,
  Notice,
  PageHeader,
  Sources,
} from '../../shared/components/UI'

import { createExam, getExam } from './api'
import type { ExamQuestion, ExamRecord } from './api'

import '../practice/practice.css'

export default function ExamReportPage({
  courseId,
  examId,
}: {
  courseId: string
  examId: string
}) {
  const { loadPlan, plans } = useStudy()
  const [exam, setExam] =
    useState<ExamRecord | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [wrongOnly, setWrongOnly] = useState(false)

  useEffect(() => {
    let active = true
    getExam(Number(courseId), Number(examId))
      .then((result) => {
        if (active) setExam(result)
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [courseId, examId])

  useEffect(() => {
    void loadPlan(Number(courseId))
  }, [courseId, loadPlan])

  if (error && !exam) {
    return (
      <Empty title="Report unavailable">
        <p>{error}</p>
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </Empty>
    )
  }

  if (!exam) {
    return <Loading text="Loading the exam report…" />
  }

  if (exam.status !== 'finished' || !exam.report) {
    return (
      <Empty title="This exam is not finished">
        <Link href={`/exams/${courseId}/${examId}`}>
          Continue the exam
        </Link>
      </Empty>
    )
  }

  const report = exam.report
  const review = plans[Number(courseId)]?.plan?.tasks.find(
    task => task.kind === 'Review' && task.chapterId === String(exam.chapter_id) && task.status !== 'Completed',
  )
  const examQuestions = exam.questions.filter((item) => item.correct !== undefined)
  const shown = examQuestions.filter((item) => !wrongOnly || !item.correct)

  return (
    <div className="practice-session stack">
      <PageHeader
        eyebrow="Exam report"
        title={exam.chapter_title}
        subtitle={
          report.passed
            ? 'Passed. The next exam still covers every concept in this chapter.'
            : 'Not passed. The next exam still covers every concept in this chapter.'
        }
      />

      <section className="panel">
        <p className="chapter-score">
          Score
          <strong>{report.score}%</strong>
        </p>
        <p>
          {report.correct_count} of {report.total} questions correct.
          {' '}
          {report.wrong_count} wrong.
        </p>
        <p>
          <span className={`badge ${report.passed ? '' : 'warning'}`}>
            {report.passed ? 'Passed' : 'Not passed'}
          </span>
        </p>
      </section>

      {!report.passed && review && (
        <Notice>
          {review.date ? `Review added to your calendar starting ${prettyDate(review.date, true)}.`
            : 'Review added to your tasks. Replan or add study time to schedule it.'}
          {' '}
          <Link href={review.date ? `/calendar?course=${courseId}&date=${review.date}` : `/courses/${courseId}/info`}>
            {review.date ? 'View calendar' : 'Course settings'}
          </Link>
        </Notice>
      )}

      <section className="stack">
        <div className="actions spread">
          <h2>Questions</h2>
          <div className="report-filter">
            <button
              className={`button small ${wrongOnly ? 'secondary' : ''}`}
              type="button"
              aria-pressed={!wrongOnly}
              onClick={() => setWrongOnly(false)}
            >
              All
            </button>
            <button
              className={`button small ${wrongOnly ? '' : 'secondary'}`}
              type="button"
              aria-pressed={wrongOnly}
              onClick={() => setWrongOnly(true)}
            >
              Wrong only
            </button>
          </div>
        </div>
        {shown.length === 0 && (
          <p className="muted">
            {wrongOnly ? 'No wrong answers.' : 'No answers.'}
          </p>
        )}
        {shown.map((item) => (
          <article className="panel" key={item.id}>
            <div className="actions spread">
              <p className="eyebrow">
                {item.concept_name}
                {' · '}
                {item.kind === 'mcq' ? 'Multiple choice' : 'Short answer'}
              </p>
              <span className="badge">
                {item.correct ? 'Correct' : 'Wrong'}
              </span>
            </div>
            <h3>{item.prompt}</h3>
            <p>
              <strong>Your answer. </strong>
              {givenAnswer(item)}
            </p>
            <p>
              <strong>Expected. </strong>
              {expectedAnswer(item)}
            </p>
            {item.explanation && <p>{item.explanation}</p>}
            <Sources sources={item.sources} />
          </article>
        ))}
      </section>

      {error && <Notice tone="error">{error}</Notice>}

      <div className="actions">
        <button
          className="button"
          disabled={busy}
          onClick={() => {
            setBusy(true)
            setError('')
            void createExam(Number(courseId), exam.chapter_id)
              .then(async (created) => {
                await loadPlan(Number(courseId))
                navigate(`/exams/${courseId}/${created.id}`)
              })
              .catch((reason) => {
                setError(messageOf(reason))
                setBusy(false)
              })
          }}
        >
          {busy ? 'Writing exam…' : 'Start another exam'}
        </button>
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </div>
    </div>
  )
}

function expectedAnswer(question: ExamQuestion) {
  return choiceText(question.answer || '', question.kind, question.options)
}

function givenAnswer(question: ExamQuestion) {
  const text = choiceText(question.response || '', question.kind, question.options)
  return text || 'Blank'
}

function choiceText(value: string, kind: string, options: string[] = []) {
  const letter = value.trim().toUpperCase().slice(0, 1)
  if (kind === 'mcq' && letter) {
    const option = options[letter.charCodeAt(0) - 65]
    if (option) return `${letter}. ${option}`
  }
  return value
}
