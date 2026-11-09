import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

import {
  Link,
  navigate,
} from '../../shared/router'
import { messageOf } from '../../shared/request'
import {
  Empty,
  Loading,
  Notice,
  PageHeader,
  Sources,
} from '../../shared/components/UI'

import {
  getExam,
  saveExamDraft,
  submitExam,
} from './api'
import type { ExamRecord } from './api'

import '../practice/practice.css'

export default function ExamPage({
  courseId,
  examId,
}: {
  courseId: string
  examId: string
}) {
  const [exam, setExam] =
    useState<ExamRecord | null>(null)
  const [answers, setAnswers] = useState<
    Record<number, string>
  >({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState('')
  const skipSave = useRef(true)

  useEffect(() => {
    let active = true
    getExam(Number(courseId), Number(examId))
      .then((result) => {
        if (!active) return
        if (result.status === 'finished') {
          navigate(
            `/exams/${courseId}/${examId}/report`,
            true,
          )
          return
        }
        setExam(result)
        const restored: Record<number, string> = {}
        for (const question of result.questions) {
          if (question.response) restored[question.id] = question.response
        }
        setAnswers(restored)
        skipSave.current = true
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [courseId, examId])

  useEffect(() => {
    if (!exam || exam.status === 'finished') return
    if (skipSave.current) {
      skipSave.current = false
      return
    }
    const handle = window.setTimeout(() => {
      void saveExamDraft(
        Number(courseId),
        exam.id,
        exam.questions.map((question) => ({
          question_id: question.id,
          response: answers[question.id] || '',
        })),
      )
        .then(() => setSaved('Saved'))
        .catch(() => setSaved(''))
    }, 500)
    return () => window.clearTimeout(handle)
  }, [answers, courseId, exam])

  async function onSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()
    if (!exam || busy) return
    const missing = exam.questions.some(
      (question) =>
        !answers[question.id]?.trim(),
    )
    if (missing) {
      setError('Answer every question before submitting.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await submitExam(
        Number(courseId),
        exam.id,
        exam.questions.map((question) => ({
          question_id: question.id,
          response: answers[question.id] || '',
        })),
      )
      navigate(`/exams/${courseId}/${exam.id}/report`)
    } catch (reason) {
      setError(messageOf(reason))
      setBusy(false)
    }
  }

  if (error && !exam) {
    return (
      <Empty title="Exam unavailable">
        <p>{error}</p>
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </Empty>
    )
  }

  if (!exam) {
    return <Loading text="Loading your exam…" />
  }

  return (
    <form
      className="practice-session stack"
      onSubmit={onSubmit}
    >
      <PageHeader
        eyebrow="Chapter exam"
        title={exam.chapter_title}
        subtitle="80% of the questions must be correct. A short answer is correct when it covers at least 80% of its points. Answers are saved while you work."
      />

      {error && <Notice tone="error">{error}</Notice>}

      {exam.questions.map((question, index) => (
        <fieldset
          className="panel question-card"
          key={question.id}
        >
          <div className="actions spread">
            <span className="eyebrow">
              Question {index + 1}
              {' · '}
              {question.concept_name}
            </span>
            <span className="badge">
              {question.kind === 'mcq'
                ? 'Multiple choice'
                : 'Short answer'}
            </span>
          </div>

          <h2>{question.prompt}</h2>

          {question.kind === 'mcq' ? (
            <div className="question-options">
              {question.options.map((option, optionIndex) => {
                const letter = String.fromCharCode(65 + optionIndex)
                return (
                  <label
                    key={letter}
                    className={
                      answers[question.id] === letter
                        ? 'selected'
                        : ''
                    }
                  >
                    <input
                      type="radio"
                      name={`question-${question.id}`}
                      checked={answers[question.id] === letter}
                      value={letter}
                      onChange={() =>
                        setAnswers((current) => ({
                          ...current,
                          [question.id]: letter,
                        }))
                      }
                    />
                    <span className="option-letter">
                      {letter}
                    </span>
                    <span>{option}</span>
                  </label>
                )
              })}
            </div>
          ) : (
            <label className="field">
              <span className="sr-only">
                Your answer to question {index + 1}
              </span>
              <textarea
                rows={4}
                maxLength={5000}
                value={answers[question.id] || ''}
                onChange={(event) =>
                  setAnswers((current) => ({
                    ...current,
                    [question.id]: event.target.value,
                  }))
                }
              />
            </label>
          )}

          <Sources sources={question.sources} />
        </fieldset>
      ))}

      <div className="actions">
        <button className="button" disabled={busy}>
          {busy ? 'Grading…' : 'Submit exam'}
        </button>
        {saved && <span className="muted small">{saved}</span>}
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </div>
    </form>
  )
}
