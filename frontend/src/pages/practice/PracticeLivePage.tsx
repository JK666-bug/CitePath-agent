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
  answerPractice,
  createPractice,
  getPractice,
  practiceOutcome,
  retryPracticeExplanation,
  savePracticeDraft,
} from './api'
import type { PracticeSession } from './api'
import RoundSummary, { PassThreshold } from './RoundSummary'
import ExplanationFeedback from '../../shared/components/ExplanationFeedback'
import ReportNarrative from '../../shared/components/ReportNarrative'
import MarkingPoints from '../../shared/components/MarkingPoints'

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
  const [savedResponse, setSavedResponse] = useState('')
  const [saveError, setSaveError] = useState('')
  const [newThreshold, setNewThreshold] = useState(0.8)
  const [retryingQuestion, setRetryingQuestion] = useState<number | null>(null)
  const [feedbackError, setFeedbackError] = useState('')
  const draftQueue = useRef<Promise<void>>(Promise.resolve())
  const currentQuestionId = useRef(0)

  useEffect(() => {
    let active = true
    getPractice(Number(courseId), Number(sessionId))
      .then((result) => {
        if (active) {
          setSession(result)
          setResponse(result.question?.response ?? '')
          setSavedResponse(result.question?.response ?? '')
          setNewThreshold(result.passing_threshold ?? 0.8)
        }
      })
      .catch((reason) => {
        if (active) setError(messageOf(reason))
      })
    return () => {
      active = false
    }
  }, [courseId, sessionId])

  const questionId = session?.question?.id
  useEffect(() => {
    currentQuestionId.current = questionId ?? 0
    return () => { currentQuestionId.current = 0 }
  }, [questionId])
  useEffect(() => {
    if (!questionId || busy || retryingQuestion !== null || response === savedResponse) return
    const timer = window.setTimeout(() => {
      const request = draftQueue.current.then(() =>
        savePracticeDraft(Number(courseId), Number(sessionId), questionId, response),
      )
      draftQueue.current = request.then(() => undefined, () => undefined)
      request.then(() => {
        if (currentQuestionId.current === questionId) {
          setSavedResponse(response)
          setSaveError('')
        }
      }).catch((reason) => {
        if (currentQuestionId.current === questionId) {
          setSaveError(`Draft not saved. ${messageOf(reason)}`)
        }
      })
    }, 600)
    return () => window.clearTimeout(timer)
  }, [busy, courseId, questionId, response, retryingQuestion, savedResponse, sessionId])

  async function retryExplanation(questionId: number) {
    if (!session || busy || retryingQuestion !== null) return
    setRetryingQuestion(questionId)
    setFeedbackError('')
    try {
      await draftQueue.current
      const next = await retryPracticeExplanation(Number(courseId), session.id, questionId)
      setSession(next)
      // A feedback retry must not overwrite a draft being written for the next question.
      if (next.question?.id !== session.question?.id) {
        setResponse(next.question?.response ?? '')
        setSavedResponse(next.question?.response ?? '')
      }
    } catch (reason) {
      setFeedbackError(`Could not retry the explanation. ${messageOf(reason)}`)
    } finally {
      setRetryingQuestion(null)
    }
  }

  async function saveCurrentDraft() {
    if (!session?.question) return
    await draftQueue.current
    await savePracticeDraft(Number(courseId), session.id, session.question.id, response)
    setSavedResponse(response)
    setSaveError('')
  }

  async function onSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()
    if (!session?.question || busy || retryingQuestion !== null) return
    if (!response.trim()) {
      setError('Write an answer before continuing.')
      return
    }
    setBusy(true)
    setError('')
    try {
      // Finish older draft writes first. The answer endpoint saves this response
      // itself, and also accepts retries after grading or next-round generation.
      await draftQueue.current
      const next = await answerPractice(
        Number(courseId),
        session.id,
        session.question.id,
        response,
      )
      setSession(next)
      setResponse(next.question?.response ?? '')
      setSavedResponse(next.question?.response ?? '')
      setSaveError('')
    } catch (reason) {
      setError(`${messageOf(reason)} Your answer is kept on this page. Retry to continue; an incomplete grading result does not produce a chapter score.`)
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
  const threshold = session.passing_threshold ?? report?.passing_threshold ?? 0.8
  const roundNumber = session.round_number ?? (session.phase === 'review' ? 2 : 1)
  const rounds = report?.rounds ?? session.round_results ?? []
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

        {session.migration_notice && <Notice>{session.migration_notice}</Notice>}

        <Notice tone={report.passed ? 'success' : 'info'}>
          {practiceOutcome(report.outcome)}
        </Notice>

        {rounds.length > 0 && <RoundSummary rounds={rounds} threshold={threshold} />}

        <ReportNarrative report={report} courseId={courseId} />
        {feedbackError && <Notice tone="error">{feedbackError}</Notice>}

        <section className="panel">
          <p className="chapter-score">
            Answered
            <strong>{report.question_count}</strong>
          </p>
          <p>
            {report.correct_count} correct. {report.wrong_count} wrong.
            {' '}These counts describe all answers in this session.
          </p>
        </section>

        {(report.remaining_weak_concepts?.length ?? 0) > 0 && (
          <section className="panel stack">
            <h2>Remaining weak concepts</h2>
            <p>{report.remaining_weak_concepts!.join(' · ')}</p>
            <Sources sources={report.remaining_sources ?? []} courseId={courseId} />
          </section>
        )}

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
              {item.kind === 'short' && <MarkingPoints {...item} />}
              {!item.correct && (
                <ExplanationFeedback
                  {...item}
                  busy={retryingQuestion === item.question_id}
                  disabled={retryingQuestion !== null || starting}
                  onRetry={() => { void retryExplanation(item.question_id) }}
                />
              )}
              <Sources sources={item.sources} courseId={courseId} />
            </article>
          ))}
        </section>

        {error && <Notice tone="error">{error}</Notice>}

        <section className="panel stack">
          <h2>Start a new chapter session</h2>
          <p className="muted small">
            This report stays saved. A new session starts at round 1 and has its own two-round limit.
          </p>
          <PassThreshold value={newThreshold} onChange={setNewThreshold} disabled={starting} />
        <div className="actions">
          <button
            className="button"
            type="button"
            disabled={starting || retryingQuestion !== null}
            onClick={() => {
              setError('')
              setStarting(true)
              void createPractice(Number(courseId), session.chapter_id, newThreshold)
                .then((created) =>
                  navigate(`/practice/${courseId}/sessions/${created.id}`),
                )
                .catch((reason) => {
                  setError(messageOf(reason))
                  setStarting(false)
                })
            }}
          >
            {starting ? 'Preparing session…' : 'Start new session'}
          </button>
          <Link href={`/courses/${courseId}/plan`}>
            Back to plan
          </Link>
        </div>
        </section>
      </div>
    )
  }

  return (
    <form
      className="practice-session stack"
      onSubmit={onSubmit}
    >
      <PageHeader
        eyebrow={`Chapter practice · Round ${roundNumber} of 2`}
        title={session.chapter_title}
        subtitle={
          `Chapter pass mark: ${Math.round(threshold * 100)}%. ` +
          (roundNumber === 2
            ? 'This final round targets weak concepts from round 1.'
            : 'Answer each question. Passing this round completes the chapter session.')
        }
      />

      {error && <Notice tone="error">{error}</Notice>}
      {session.migration_notice && <Notice>{session.migration_notice}</Notice>}
      {saveError && <Notice tone="error">{saveError}</Notice>}
      {feedbackError && <Notice tone="error">{feedbackError}</Notice>}

      {rounds.length > 0 && <RoundSummary rounds={rounds} threshold={threshold} />}

      {typeof session.round_question_count === 'number' && (
        <p className="muted small">
          {session.answered_count ?? 0} of {session.round_question_count} answers saved in this round.
          A round score appears after every question has been graded.
        </p>
      )}

      {session.feedback && (
        <div className="stack">
        <Notice tone={session.feedback.correct ? 'success' : 'error'}>
          <strong>{session.feedback.concept_name}</strong>
          {session.feedback.correct
            ? ' is correct.'
            : ` needs another look. Expected: ${session.feedback.answer}`}
        </Notice>
        {!session.feedback.correct && (
          <ExplanationFeedback
            {...session.feedback}
            busy={retryingQuestion === session.feedback.question_id}
            disabled={busy || retryingQuestion !== null}
            onRetry={session.feedback.question_id === undefined ? undefined : () => {
              void retryExplanation(session.feedback!.question_id!)
            }}
          />
        )}
        {!session.feedback.correct && <Sources sources={session.feedback.sources ?? []} courseId={courseId} />}
        <MarkingPoints {...session.feedback} />
        </div>
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
        <fieldset className="panel question-card" disabled={busy || retryingQuestion !== null}>
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

          <Sources sources={question.sources} courseId={courseId} />
        </fieldset>
      ) : (
        <p className="muted">This practice session is complete.</p>
      )}

      <div className="actions">
        {question && (
          <button className="button" disabled={busy || retryingQuestion !== null}>
            {busy ? 'Checking…' : 'Submit answer'}
          </button>
        )}
        {question && (
          <button
            type="button"
            className="button secondary"
            disabled={busy || retryingQuestion !== null || response === savedResponse}
            onClick={() => {
              setBusy(true)
              void saveCurrentDraft()
                .catch((reason) => setSaveError(`Draft not saved. ${messageOf(reason)}`))
                .finally(() => setBusy(false))
            }}
          >
            Save answer draft
          </button>
        )}
        <Link href={`/courses/${courseId}/plan`}>
          Back to plan
        </Link>
      </div>
      {question && (
        <p className="practice-save-status" role="status">
          {response === savedResponse
            ? 'Draft saved to your account. Reopening restores this question and answer.'
            : 'Saving your draft… Keep this page open until it is saved.'}
        </p>
      )}
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
