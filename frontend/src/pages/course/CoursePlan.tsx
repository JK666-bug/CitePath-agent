import {
  useEffect,
  useState,
} from 'react'

import {
  BookOpen,
  PencilLine,
  RotateCcw,
} from 'lucide-react'

import type { CourseDetail, Task } from './types'
import { decodeBrief } from '../courseEditor/brief'

import { createExam } from '../exam/api'
import PracticeStartModal from '../practice/PracticeStartModal'
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

import DocumentPicker, {
  usableMaterials,
} from './DocumentPicker'
import TaskDetails from './TaskDetails'

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
  const [practiceChapterId, setPracticeChapterId] =
    useState<number | null>(null)
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

  const materials = usableMaterials(course.documents)
  const ready = materials.length > 0

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
            Choose the PDFs this plan should
            use, then set the first and last
            study day. You can generate another
            plan later from different PDFs in
            this course.
          </p>

          {!ready && (
            <p>
              Upload a readable PDF on the
              Course information tab first.
            </p>
          )}

          <PlanDates
            key={`${windowStart}:${windowEnd}:${config.note}:${materials.map((item) => item.id).join(',')}`}
            initialStart={windowStart}
            initialEnd={windowEnd}
            initialNote={config.note}
            documents={course.documents}
            busy={!ready || Boolean(entry?.generating)}
            label={
              entry?.generating
                ? 'Creating your plan…'
                : 'Generate plan'
            }
            onGenerate={(start, end, note, documentIds) =>
              void generateCoursePlan(
                numericId,
                start,
                end,
                note,
                documentIds,
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
        </Notice>
      )}

      {entry?.generating && (
        <Notice>
          Creating a new plan from your note
          and lecture pages…
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

      {!isDemo && (
        <section className="panel">
          <h2>Plan dates</h2>

          <p className="muted small">
            Choose which PDFs to include.
            Regenerating replaces this plan, so
            you can switch to another set of
            PDFs in the same course.
          </p>

          <PlanDates
            key={`${plan.version}:${windowStart}:${windowEnd}:${config.note}:${materials.map((item) => item.id).join(',')}`}
            initialStart={windowStart}
            initialEnd={windowEnd}
            initialNote={config.note}
            documents={course.documents}
            busy={Boolean(entry?.generating)}
            label={
              entry?.generating
                ? 'Creating your plan…'
                : 'Regenerate plan'
            }
            onGenerate={(start, end, note, documentIds) => {
              if (
                window.confirm(
                  'Save this study brief and generate a new plan? Completed tasks in this plan will be reset.',
                )
              ) {
                void generateCoursePlan(
                  numericId,
                  start,
                  end,
                  note,
                  documentIds,
                )
              }
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
              </div>

              <Sources
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
                        </p>
                      </div>

                      <div className="plan-task-actions">
                        {task.kind === 'Practice' ? (
                          isDemo ? (
                            <>
                              <Link
                                className="button small"
                                href={
                                  `/practice/demo/${task.chapterId}`
                                }
                              >
                                Practice
                              </Link>
                              <button
                                className="button small secondary"
                                disabled={
                                  task.status === 'Completed' ||
                                  entry?.generating
                                }
                                onClick={() => markComplete(task)}
                              >
                                Done
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                className="button small"
                                onClick={() => {
                                  setExamError('')
                                  setPracticeChapterId(
                                    Number(task.chapterId),
                                  )
                                }}
                              >
                                Practice
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
                                  ? 'Wait…'
                                  : 'Exam'}
                              </button>
                            </>
                          )
                        ) : task.kind === 'Review' ? (
                          <>
                            {isDemo ? (
                              <span className="plan-task-action-slot" />
                            ) : (
                              <Link
                                className="button small"
                                href={
                                  `/courses/${courseId}/chapters/${task.chapterId}/reports`
                                }
                              >
                                Reports
                              </Link>
                            )}
                            <button
                              className="button small secondary"
                              disabled={
                                task.status === 'Completed' ||
                                entry?.generating
                              }
                              onClick={() => markComplete(task)}
                            >
                              Done
                            </button>
                          </>
                        ) : task.kind === 'Reading' && !isDemo ? (
                          <>
                            <Link
                              className="button small"
                              href={
                                `/courses/${courseId}/read?task=` +
                                encodeURIComponent(task.id)
                              }
                            >
                              Open
                            </Link>
                            <button
                              className="button small secondary"
                              disabled={
                                task.status === 'Completed' ||
                                entry?.generating
                              }
                              onClick={() => markComplete(task)}
                            >
                              Done
                            </button>
                          </>
                        ) : (
                          <>
                            <span className="plan-task-action-slot" />
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
                              Done
                            </button>
                          </>
                        )}
                      </div>
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

      {!isDemo && (
        <PracticeStartModal
          open={practiceChapterId != null}
          courseId={numericId}
          chapterId={practiceChapterId}
          onClose={() => setPracticeChapterId(null)}
        />
      )}
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
  documents,
  busy,
  label,
  onGenerate,
}: {
  initialStart: string
  initialEnd: string
  initialNote: string
  documents: CourseDetail['documents']
  busy: boolean
  label: string
  onGenerate: (
    start: string,
    end: string,
    note: string,
    documentIds: number[],
  ) => void
}) {
  const ready = usableMaterials(documents)
  const [startDate, setStartDate] =
    useState(initialStart)
  const [endDate, setEndDate] =
    useState(initialEnd)
  const [note, setNote] = useState(initialNote)
  const [documentIds, setDocumentIds] = useState(
    () => ready.map((document) => document.id),
  )
  const [error, setError] = useState('')
  const invalid =
    !/^\d{4}-\d{2}-\d{2}$/.test(startDate) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(endDate) ||
    endDate < startDate

  return (
    <div className="plan-window">
      <div className="field full">
        <span>PDFs for this plan</span>
        <DocumentPicker
          documents={documents}
          selectedIds={documentIds}
          disabled={busy}
          onChange={(ids) => {
            setDocumentIds(ids)
            setError('')
          }}
        />
      </div>

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
          <span>Study brief</span>

          <textarea
            rows={4}
            maxLength={9000}
            value={note}
            disabled={busy}
            onChange={(event) =>
              setNote(event.target.value)
            }
            placeholder="Goals, background, and what you want this plan to emphasize."
          />
        </label>
      </div>

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
            if (!documentIds.length) {
              setError('Select at least one PDF.')
              return
            }
            if (invalid) {
              setError(
                'Choose a start date and an end date on or after it.',
              )
              return
            }

            onGenerate(
              startDate,
              endDate,
              note,
              documentIds,
            )
          }}
        >
          {label}
        </button>
      </div>
    </div>
  )
}

