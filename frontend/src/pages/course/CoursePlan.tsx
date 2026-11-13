import {
  useEffect,
  useId,
  useState,
} from 'react'

import {
  BookOpen,
  PencilLine,
  RotateCcw,
} from 'lucide-react'

import type { CourseDetail, Task, PlanningProfile, PlanQuestion, MaterialUpdate } from './types'
import type { PlanOptions } from './api'
import { decodeBrief } from '../courseEditor/brief'

import { createExam } from '../exam/api'
import { createPractice } from '../practice/api'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'

import {
  Link,
  navigate,
  useLocation,
} from '../../shared/router'

import {
  addDays,
  dateKey,
  prettyDate,
} from '../../shared/format'

import {
  Empty,
  Loading,
  Notice,
  Sources,
} from '../../shared/components/UI'

import PaceLine, {
  ProgressTrack,
  taskTotals,
} from '../../shared/components/PaceLine'

import TaskDetails from './TaskDetails'
import { EstimatedWorkload, PlanHistory } from './PlanningDetails'

export default function CoursePlan({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const {
    demo,
    completeTask,
    plans,
    loadPlan,
    generateCoursePlan,
    finishPlanTask,
  } = useStudy()

  const { search } = useLocation()
  const [startingChapter, setStartingChapter] =
    useState('')
  const [examError, setExamError] =
    useState('')
  const isDemo = courseId === 'demo'
  const numericId = Number(courseId)
  const entry = plans[numericId]

  useEffect(() => {
    if (!isDemo) {
      void loadPlan(numericId)
    }
  }, [isDemo, loadPlan, numericId])

  if (!isDemo && !entry?.loaded) {
    return (
      <Loading text="Loading your study plan…" />
    )
  }

  const plan = isDemo
    ? demo.plan
    : entry?.plan

  const config =
    decodeBrief(course.student_brief)

  const windowStart =
    plan?.start || dateKey()

  const windowEnd = suggestedEnd(
    config.deadline,
    config.earlyDays,
    windowStart,
    plan?.end,
  )

  const ready = course.documents.some(
    (document) =>
      document.ingest_status === 'complete' &&
      document.usable_page_count > 0,
  )

  function markComplete(task: Task) {
    if (isDemo) {
      completeTask(task.id)
      return
    }

    void finishPlanTask(numericId, task.id)
  }

  if (!plan) {
    return (
      <div className="stack">
        {entry?.error && (
          <Notice tone="error">
            {entry.error}
          </Notice>
        )}

        <Empty title="Generate a study plan">
          <p>
            Choose the first and last study
            day. The plan reads your goals and
            lecture pages, then spreads
            reading, practice, and review
            across those dates.
          </p>

          {!ready && (
            <p>
              Upload a readable PDF on the
              Course information tab first.
            </p>
          )}

          <PlanDates
            key={`${windowStart}:${windowEnd}:${config.note}`}
            initialStart={windowStart}
            initialEnd={windowEnd}
            initialNote={config.note}
            initialProfile={entry?.profile}
            questions={entry?.questions}
            busy={!ready || Boolean(entry?.generating)}
            label={
              entry?.generating
                ? 'Creating your plan…'
                : 'Generate plan'
            }
            onGenerate={(start, end, note, options) =>
              void generateCoursePlan(
                numericId,
                start,
                end,
                note,
                options,
              )
            }
          />
        </Empty>
      </div>
    )
  }

  const totals = taskTotals(plan.tasks)

  const selected =
    plan.tasks.find(
      (task) =>
        task.id === search.get('task'),
    ) || null

  return (
    <div className="stack">
      {!isDemo && (entry?.error || examError) && (
        <Notice tone="error">
          {examError || entry?.error}
          {entry?.error && (
            <button className="text-button" disabled={entry.loading || entry.generating} onClick={() => void loadPlan(numericId)}>
              Reload saved plan
            </button>
          )}
        </Notice>
      )}

      {entry?.generating && (
        <Notice>
          Updating your plan from your study profile, materials and results…
        </Notice>
      )}

      <div className="course-plan-overview">
        <section className="panel">
          <h2>Your course progress</h2>

          <ProgressTrack
            label="Planned tasks completed"
            done={totals.done}
            total={totals.total}
          />

          <div className="plan-stats">
            <div>
              <small>Tasks</small>
              <strong>
                {totals.done}/{totals.total}
              </strong>
            </div>

            <div>
              <small>Remaining</small>
              <strong>
                {totals.remaining}
              </strong>
            </div>

            <div>
              <small>Planned finish</small>
              <strong>
                {prettyDate(
                  plan.tasks
                    .map((task) => task.date)
                    .sort()
                    .at(-1) || plan.start,
                )}
              </strong>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>Schedule outlook</h2>

          <PaceLine
            plan={plan}
            config={config}
          />
        </section>
      </div>

      <EstimatedWorkload plan={plan} />

      {!isDemo && Boolean(entry?.material_update?.missing_document_ids.length) && (
        <Notice>
          Some sources from this saved plan are no longer uploaded. Your completed work and practice history remain saved; restore those materials to read their source pages again.
        </Notice>
      )}

      {!isDemo && (
        <section className="panel">
          <h2>Plan dates</h2>

          <p className="muted small">
            Updates unfinished tasks and keeps completed work and existing chapter history.
            Your study brief is saved on this course.
          </p>

          <PlanDates
            key={`${plan.version}:${windowStart}:${windowEnd}:${config.note}`}
            initialStart={windowStart}
            initialEnd={windowEnd}
            initialNote={config.note}
            initialProfile={entry?.profile ?? plan.planning_profile}
            questions={entry?.questions}
            materialUpdate={entry?.material_update}
            busy={Boolean(entry?.generating)}
            label={
              entry?.generating
                ? 'Rescheduling…'
                : 'Reschedule plan'
            }
            onGenerate={(start, end, note, options) => {
              void generateCoursePlan(numericId, start, end, note, { ...options, expected_version: plan.version })
            }}
          />
        </section>
      )}

      <div className="plan-version">
        <p className="muted small">
          Plan v{plan.version}
          {' · '}
          {plan.reason}
        </p>

        <div className="actions">
          {!isDemo && <PlanHistory courseId={numericId} currentVersion={plan.version} />}

          <Link
            className="button small secondary"
            href={
              `/calendar?course=${courseId}`
            }
          >
            View in calendar
          </Link>
        </div>
      </div>

      {plan.chapters.map(
        (chapter, chapterIndex) => (
          <section
            className="panel chapter-section"
            key={chapter.id}
          >
            <header>
              <div>
                <p className="eyebrow">
                  Chapter {chapterIndex + 1}
                </p>

                <h2>{chapter.title}</h2>

                <p className="muted small">
                  {chapter.concepts.join(' · ')}
                </p>
                {typeof chapter.estimated_minutes === 'number' && (
                  <p className="muted small">Estimated chapter work: {chapter.estimated_minutes} min</p>
                )}
              </div>

              <Sources
                courseId={courseId}
                sources={chapter.sources}
              />
            </header>

            <div className="plan-task-list">
              {plan.tasks
                .filter(
                  (task) =>
                    task.chapterId ===
                    chapter.id,
                )
                .map((task) => {
                  const Icon =
                    task.kind === 'Reading'
                      ? BookOpen
                      : task.kind === 'Practice'
                        ? PencilLine
                        : RotateCcw

                  return (
                    <article
                      className={
                        `plan-task ${
                          task.status ===
                          'Completed'
                            ? 'completed'
                            : ''
                        }`
                      }
                      key={task.id}
                    >
                      <span
                        className={
                          `task-symbol ` +
                          task.kind.toLowerCase()
                        }
                      >
                        <Icon
                          size={17}
                          strokeWidth={1.5}
                        />
                      </span>

                      <div className="plan-task-body">
                        <button
                          className="task-title"
                          onClick={() =>
                            navigate(
                              `/courses/${courseId}/plan?task=` +
                                encodeURIComponent(
                                  task.id,
                                ),
                            )
                          }
                        >
                          {task.title}
                        </button>

                        <p className="muted small">
                          {prettyDate(task.date)}
                          {' · '}
                          Step{' '}
                          {plan.tasks.findIndex(
                            (item) =>
                              item.id === task.id,
                          ) + 1}
                          {typeof task.estimated_minutes === 'number' && ` · ${task.estimated_minutes} estimated min`}
                        </p>
                      </div>

                      <span className="badge">
                        {task.status}
                      </span>

                      {task.kind ===
                      'Practice' ? (
                        isDemo ? (
                          <Link
                            className="button small secondary"
                            href={
                              `/practice/demo/${task.chapterId}`
                            }
                          >
                            Open practice
                          </Link>
                        ) : (
                          <div className="plan-task-actions">
                            <button
                              className="button small"
                              disabled={
                                startingChapter ===
                                `practice-${task.chapterId}`
                              }
                              onClick={() => {
                                setExamError('')
                                setStartingChapter(
                                  `practice-${task.chapterId}`,
                                )
                                void createPractice(
                                  numericId,
                                  Number(task.chapterId),
                                )
                                  .then((created) =>
                                    navigate(
                                      `/practice/${courseId}/sessions/${created.id}`,
                                    ),
                                  )
                                  .catch((reason) => {
                                    setExamError(
                                      messageOf(reason),
                                    )
                                    setStartingChapter('')
                                  })
                              }}
                            >
                              {startingChapter ===
                              `practice-${task.chapterId}`
                                ? 'Writing question…'
                                : 'Start practice'}
                            </button>
                            <button
                              className="button small secondary"
                              disabled={
                                startingChapter ===
                                `exam-${task.chapterId}`
                              }
                              onClick={() => {
                                setExamError('')
                                setStartingChapter(
                                  `exam-${task.chapterId}`,
                                )
                                void createExam(
                                  numericId,
                                  Number(task.chapterId),
                                )
                                  .then((created) =>
                                    navigate(
                                      `/exams/${courseId}/${created.id}`,
                                    ),
                                  )
                                  .catch((reason) => {
                                    setExamError(
                                      messageOf(reason),
                                    )
                                    setStartingChapter('')
                                  })
                              }}
                            >
                              {startingChapter ===
                              `exam-${task.chapterId}`
                                ? 'Writing exam…'
                                : 'Start exam'}
                            </button>
                          </div>
                        )
                      ) : task.kind === 'Review' && !isDemo ? (
                        <Link
                          className="button small"
                          href={
                            `/courses/${courseId}/chapters/${task.chapterId}/reports`
                          }
                        >
                          View reports
                        </Link>
                      ) : (
                        <button
                          className="button small secondary"
                          disabled={
                            task.status ===
                              'Completed' ||
                            entry?.generating
                          }
                          onClick={() =>
                            markComplete(task)
                          }
                        >
                          {task.status ===
                          'Completed'
                            ? 'Done'
                            : 'Mark complete'}
                        </button>
                      )}
                    </article>
                  )
                })}
            </div>
          </section>
        ),
      )}

      <TaskDetails
        task={selected}
        courseId={courseId}
        onClose={() =>
          navigate(`/courses/${courseId}/plan`)
        }
        onComplete={markComplete}
      />
    </div>
  )
}

function suggestedEnd(
  deadline: string,
  earlyDays: number,
  start: string,
  saved?: string,
) {
  if (
    saved &&
    /^\d{4}-\d{2}-\d{2}$/.test(saved) &&
    saved >= start
  ) {
    return saved
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(deadline)) {
    const early = addDays(deadline, -earlyDays)
    return early >= start ? early : deadline
  }

  return addDays(start, 14)
}

function PlanDates({
  initialStart,
  initialEnd,
  initialNote,
  initialProfile,
  questions = [],
  materialUpdate,
  busy,
  label,
  onGenerate,
}: {
  initialStart: string
  initialEnd: string
  initialNote: string
  initialProfile?: Partial<PlanningProfile>
  questions?: PlanQuestion[]
  materialUpdate?: MaterialUpdate
  busy: boolean
  label: string
  onGenerate: (
    start: string,
    end: string,
    note: string,
    options: PlanOptions,
  ) => void
}) {
  const fieldId = useId()
  const [startDate, setStartDate] =
    useState(initialStart)
  const [endDate, setEndDate] =
    useState(initialEnd)
  const [note, setNote] = useState(initialNote)
  const [goal, setGoal] = useState(initialProfile?.goal ?? '')
  const [priorKnowledge, setPriorKnowledge] = useState(initialProfile?.prior_knowledge ?? '')
  const [dailyMinutes, setDailyMinutes] = useState(initialProfile?.daily_minutes?.toString() ?? '')
  const [readingPace, setReadingPace] = useState(String(initialProfile?.reading_words_per_minute ?? 180))
  const [includeNewMaterials, setIncludeNewMaterials] = useState(false)
  const [error, setError] = useState('')
  const invalid =
    !/^\d{4}-\d{2}-\d{2}$/.test(startDate) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(endDate) ||
    endDate < startDate

  return (
    <div className="plan-window">
      {questions.length > 0 && (
        <Notice>
          <strong>A few details will make this plan useful.</strong>
          <ul>{questions.map((question) => <li key={question.id}>{question.prompt}</li>)}</ul>
          <p>Your current plan stays saved while you complete these details.</p>
        </Notice>
      )}
      <div className="form-grid">
        <label className="field">
          <span>Start date</span>

          <input
            type="date"
            value={startDate}
            disabled={busy}
            aria-invalid={Boolean(error)}
            onChange={(event) => {
              setStartDate(event.target.value)
              setError('')
            }}
          />
        </label>

        <label className="field">
          <span>End date</span>

          <input
            type="date"
            value={endDate}
            disabled={busy}
            aria-invalid={Boolean(error)}
            onChange={(event) => {
              setEndDate(event.target.value)
              setError('')
            }}
          />
        </label>

        <label className="field full">
          <span>Learning goal</span>
          <input value={goal} maxLength={2000} disabled={busy} aria-invalid={questions.some((q) => q.id === 'goal') && !goal.trim()}
            onChange={(event) => setGoal(event.target.value)} placeholder="What should you be able to do by the end?" />
        </label>
        <label className="field full">
          <span id={`${fieldId}-prior`}>Prior knowledge</span>
          <textarea rows={2} maxLength={2000} value={priorKnowledge} disabled={busy}
            aria-labelledby={`${fieldId}-prior`}
            aria-invalid={questions.some((q) => q.id === 'prior_knowledge') && !priorKnowledge.trim()}
            onChange={(event) => setPriorKnowledge(event.target.value)} placeholder="What have you studied already? Which concepts feel unfamiliar?" />
        </label>
        <label className="field">
          <span>Available study minutes per day</span>
          <input type="number" min={1} max={1440} value={dailyMinutes} disabled={busy}
            aria-invalid={questions.some((q) => q.id === 'daily_minutes') && !dailyMinutes}
            onChange={(event) => setDailyMinutes(event.target.value)} placeholder="For example, 45" />
        </label>
        <label className="field">
          <span id={`${fieldId}-pace`}>Estimated reading pace (words per minute)</span>
          <input type="number" min={1} max={1200} value={readingPace} disabled={busy} aria-labelledby={`${fieldId}-pace`} onChange={(event) => setReadingPace(event.target.value)} />
          <small className="muted">A planning assumption; adjust it to your reading pace.</small>
        </label>
        <label className="field full">
          <span id={`${fieldId}-brief`}>Study brief and preferences</span>

          <textarea
            rows={4}
            maxLength={9000}
            value={note}
            aria-labelledby={`${fieldId}-brief`}
            disabled={busy}
            onChange={(event) =>
              setNote(event.target.value)
            }
            placeholder="Goals, background, and what you want this plan to emphasize."
          />
        </label>
      </div>

      {materialUpdate && materialUpdate.new_page_count > 0 && (
        <div className="plan-material-update stack">
          <strong>New material available</strong>
          <p>{materialUpdate.new_page_count} teaching {materialUpdate.new_page_count === 1 ? 'page' : 'pages'} from {materialUpdate.new_document_ids.length} {materialUpdate.new_document_ids.length === 1 ? 'document' : 'documents'} are outside this plan.</p>
          <label className="checkbox-field">
            <input type="checkbox" checked={includeNewMaterials} disabled={busy || !materialUpdate.can_update} onChange={(event) => setIncludeNewMaterials(event.target.checked)} />
            Include new materials when updating this plan
          </label>
          <p className="muted small">Existing chapters, completed tasks and saved practice results stay linked to their original history. New material adds new chapter work.</p>
          {!materialUpdate.can_update && <p className="muted small">Finish material ingestion before including these pages.</p>}
        </div>
      )}

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      <div className="actions">
        <button
          className="button"
          disabled={busy}
          onClick={() => {
            if (invalid) {
              setError(
                'Choose a start date and an end date on or after it.',
              )
              return
            }
            if ((dailyMinutes && (!Number.isInteger(Number(dailyMinutes)) || Number(dailyMinutes) < 1 || Number(dailyMinutes) > 1440)) || !Number.isFinite(Number(readingPace)) || Number(readingPace) < 1 || Number(readingPace) > 1200) {
              setError('Enter a daily budget from 1 to 1,440 minutes and a reading pace from 1 to 1,200 words per minute.')
              return
            }
            setError('')
            onGenerate(startDate, endDate, note, {
              profile: { goal, prior_knowledge: priorKnowledge, ...(dailyMinutes ? { daily_minutes: Number(dailyMinutes) } : {}), reading_words_per_minute: Number(readingPace) },
              update_materials: includeNewMaterials,
            })
          }}
        >
          {includeNewMaterials && !busy ? 'Include new materials and update plan' : label}
        </button>
      </div>
    </div>
  )
}

