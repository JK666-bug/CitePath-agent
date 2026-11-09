import { useEffect, useState } from 'react'
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
  answerPractice,
  createPractice,
  getPractice,
} from './api'
import type { PracticeSession } from './api'

import './practice.css'

export default function PracticeLivePage({
  courseId,
  sessionId,
}: {
  courseId: string
  sessionId: string
}) {
  const [session, setSession] =
    useState<PracticeSession | null>(null)
  const [response, setResponse] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(false)
  const [wrongOnly, setWrongOnly] = useState(false)

  useEffect(() => {
    let active = true
    getPractice(Number(courseId), Number(sessionId))
      .then((result) => {
        if (active) setSession(result)
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [courseId, sessionId])

  async function onSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()
    if (!session?.question || busy) return
    if (!response.trim()) {
      setError('Write an answer before continuing.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const next = await answerPractice(
        Number(courseId),
        session.id,
        session.question.id,
        response,
      )
      setSession(next)
      setResponse('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  if (error && !session) {
    return (
      <Empty title="Practice unavailable">
        <p>{error}</p>
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </Empty>
    )
  }

  if (!session) {
    return <Loading text="Preparing your question…" />
  }

  const question = session.question
  const report = session.report
  const practiceQuestions = report?.questions?.length
    ? report.questions
    : (report?.wrong ?? []).map((item) => ({
        ...item,
        correct: false,
      }))
  const shown = practiceQuestions.filter(
    (item) => !wrongOnly || !item.correct,
  )

  if (session.status === 'finished' && report) {
    return (
      <div className="practice-session stack">
        <PageHeader
          eyebrow="Practice report"
          title={session.chapter_title}
          subtitle={`${report.started_at} to ${report.finished_at}`}
        />

        <section className="panel">
          <p className="chapter-score">
            Answered
            <strong>{report.question_count}</strong>
          </p>
          <p>
            {report.correct_count} correct. {report.wrong_count} wrong.
            {(report.session_count ?? 0) > 1
              ? ` ${report.session_count} practice rounds.`
              : ''}
          </p>
        </section>

        <section className="stack">
          <h2>Concepts</h2>
          <ul className="practice-concepts">
            {report.concepts.map((concept) => (
              <li key={concept.name}>
                <span>
                  {concept.name}
                  {' · '}
                  {concept.correct} of {concept.attempts} correct
                </span>
                <span className="badge">
                  {concept.level >= 2 ? 'Mastered' : 'Learning'}
                </span>
              </li>
            ))}
          </ul>
        </section>

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
            <article className="panel" key={item.question_id}>
              <div className="actions spread">
                <p className="question-concept">
                  Concept: {item.concept_name}
                </p>
                <span className="badge">
                  {item.correct ? 'Correct' : 'Wrong'}
                </span>
              </div>
              <p className="eyebrow">
                {item.kind === 'mcq' ? 'Multiple choice' : 'Short answer'}
                {' · '}
                {item.phase === 'review' ? 'Review' : 'Learning'}
              </p>
              <h3>{item.prompt}</h3>
              <p>
                <strong>Your answer. </strong>
                {choiceText(item.response, item.kind, item.options)}
              </p>
              <p>
                <strong>Expected. </strong>
                {item.answer}
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
            type="button"
            disabled={starting}
            onClick={() => {
              setError('')
              setStarting(true)
              void createPractice(Number(courseId), session.chapter_id)
                .then((created) =>
                  navigate(`/practice/${courseId}/sessions/${created.id}`),
                )
                .catch((reason) => {
                  setError(messageOf(reason))
                  setStarting(false)
                })
            }}
          >
            {starting ? 'Writing question…' : 'Practice again'}
          </button>
          <Link href={`/courses/${courseId}/plan`}>
            Back to plan
          </Link>
        </div>
      </div>
    )
  }

  return (
    <form
      className="practice-session stack"
      onSubmit={onSubmit}
    >
      <PageHeader
        eyebrow={
          session.phase === 'review'
            ? 'Chapter review'
            : 'Chapter practice'
        }
        title={session.chapter_title}
        subtitle={
          session.status === 'finished'
            ? 'Every concept in this chapter is mastered.'
            : session.phase === 'review'
              ? 'These questions mix concepts you already practiced. Each question is labeled with its concept.'
              : 'Two correct answers in a row move this concept on. Each question is labeled with its concept.'
        }
      />

      {error && <Notice tone="error">{error}</Notice>}

      {session.feedback && (
        <Notice tone={session.feedback.correct ? 'success' : 'error'}>
          <strong>{session.feedback.concept_name}</strong>
          {session.feedback.correct
            ? ' is correct.'
            : ` needs another look. ${session.feedback.explanation} Expected: ${session.feedback.answer}`}
        </Notice>
      )}

      <ul className="practice-concepts">
        {session.concepts.map((concept) => (
          <li
            key={concept.id}
            className={
              question?.concept_name === concept.name
                ? 'current'
                : ''
            }
          >
            <span>{concept.name}</span>
            <span className="badge">
              {concept.level >= 2 ? 'Mastered' : 'Learning'}
            </span>
          </li>
        ))}
      </ul>

      {question ? (
        <fieldset className="panel question-card">
          <div className="actions spread">
            <p className="question-concept">
              Concept: {question.concept_name}
            </p>
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
                    className={response === letter ? 'selected' : ''}
                  >
                    <input
                      type="radio"
                      name="practice-answer"
                      checked={response === letter}
                      value={letter}
                      onChange={() => setResponse(letter)}
                    />
                    <span className="option-letter">{letter}</span>
                    <span>{option}</span>
                  </label>
                )
              })}
            </div>
          ) : (
            <label className="field">
              <span className="sr-only">
                Your answer about {question.concept_name}
              </span>
              <textarea
                rows={4}
                maxLength={5000}
                value={response}
                onChange={(event) => setResponse(event.target.value)}
              />
            </label>
          )}

          <Sources sources={question.sources} />
        </fieldset>
      ) : (
        <p className="muted">This practice session is complete.</p>
      )}

      <div className="actions">
        {question && (
          <button className="button" disabled={busy}>
            {busy ? 'Checking…' : 'Submit answer'}
          </button>
        )}
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </div>
    </form>
  )
}

function choiceText(
  value: string,
  kind: string,
  options: string[] = [],
) {
  const letter = value.trim().toUpperCase().slice(0, 1)
  if (kind === 'mcq' && letter) {
    const option = options[letter.charCodeAt(0) - 65]
    if (option) return `${letter}. ${option}`
  }
  return value || 'Blank'
}
