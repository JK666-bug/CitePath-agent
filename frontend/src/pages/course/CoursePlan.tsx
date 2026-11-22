import {
  useEffect,
  useState,
} from 'react'
import PlanHistory from './PlanHistory'
import SourceSummary from './SourceSummary'
import {
  BookOpen,
  PencilLine,
  RotateCcw,
} from 'lucide-react'

import type { Chapter, CourseDetail, Task } from './types'
import { decodeBrief } from '../courseEditor/brief'

import { createExam } from '../exam/api'
import { PracticeEntry, PracticeMastery } from '../practice/PracticeEntry'
import PracticeStartModal from '../practice/PracticeStartModal'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'

import {
  Link,
  navigate,
  useLocation,
} from '../../shared/router'

import {
  prettyDate,
} from '../../shared/format'

import {
  Loading,
  Notice,
} from '../../shared/components/UI'

import PaceLine, {
  ProgressTrack,
  taskTotals,
} from '../../shared/components/PaceLine'

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

  function markComplete(task: Task) {
    if (isDemo) {
      completeTask(task.id)
      return
    }

    if (task.kind === 'Reading') {
      void finishPlanTask(numericId, task.id)
    }
  }

  if (!plan?.chapters.length) {
    return (
      <div className="stack">
        {entry?.error && (
          <Notice tone="error">
            {entry.error}
          </Notice>
        )}

        <Notice>No chapters yet. Upload materials and analyze them in <Link href={`/courses/${courseId}/info`}>Course info</Link>.</Notice>
        {plan && !isDemo && <PlanHistory courseId={numericId} version={plan.version} />}
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
                {plan.tasks.length
                  ? prettyDate(
                      plan.tasks
                        .map((task) => task.date)
                        .filter(Boolean)
                        .sort()
                        .at(-1) || plan.start,
                    )
                  : 'Not scheduled'}
              </strong>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>Schedule outlook</h2>

          {plan.start && plan.tasks.length ? (
            <PaceLine plan={plan} config={config} />
          ) : (
            <p className="muted">
              Learning tasks are ready. Generate a daily plan to place them on the calendar.
            </p>
          )}
        </section>
      </div>

      {!isDemo && <p className="muted small">Manage materials and daily scheduling in <Link href={`/courses/${courseId}/info`}>Course info</Link>.</p>}
      {!isDemo && <PlanHistory courseId={numericId} version={plan.version} />}

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

      {plan.chapters.map((chapter, chapterIndex) => {
        const chapterTasks = plan.tasks.filter(task => task.chapterId === chapter.id)
        const review = chapterTasks.find(task => task.kind === 'Review')

        return (
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

                <div className="chapter-statuses">
                  <span className="badge">{chapterStatusLabel(chapter.chapter_status)}</span>
                  {!isDemo && (
                    <span
                      className={`badge ${chapter.review_status === 'required' ? 'warning' : ''}`}
                      title={!chapter.review_status || chapter.review_status === 'not_assessed' ? 'A review task is added if you do not pass the exam.' : undefined}
                    >
                      {reviewStatusLabel(chapter.review_status)}
                    </span>
                  )}
                </div>

                <p className="muted small">
                  {chapter.concepts.join(' · ')}
                </p>
              </div>

              <div className="chapter-card-source">
                <SourceSummary sources={chapter.sources} />
              </div>
            </header>

            <div className="plan-task-list">
              {chapterTasks
                .filter(task => task.kind !== 'Review')
                .map((task) => {
                  const Icon = task.kind === 'Reading' ? BookOpen : PencilLine
                  const realPractice = task.kind === 'Practice' && !isDemo
                  const canContinue = realPractice && chapter.practice_progress?.open_session_id != null

                  return (
                    <article
                      className={
                        `plan-task ${
                          task.status === 'Completed' && !canContinue
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
                          {task.date ? prettyDate(task.date) : 'Not scheduled'}
                          {Boolean(task.schedule?.length) && ` · ${task.estimated_minutes} min across ${task.schedule?.length} day(s)`}
                          {' · '}
                          {canContinue ? 'Practice in progress' : taskStatusLabel(task)}
                          {' · '}
                          Step{' '}
                          {plan.tasks.findIndex(
                            (item) =>
                              item.id === task.id,
                          ) + 1}
                        </p>
                        {realPractice && <PracticeMastery progress={chapter.practice_progress} />}
                      </div>

                      <div className={`plan-task-actions${realPractice ? ' plan-practice-actions' : ''}`}>
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
                              <PracticeEntry
                                courseId={courseId}
                                progress={chapter.practice_progress}
                                onStart={() => {
                                  setExamError('')
                                  setPracticeChapterId(Number(task.chapterId))
                                }}
                              />
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
                                    .then(async (created) => {
                                      await loadPlan(numericId)
                                      navigate(
                                        `/exams/${courseId}/${created.id}`,
                                      )
                                    })
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
                        ) : !isDemo ? (
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
              <ChapterReview chapter={chapter} task={review} courseId={courseId} />
            </div>
          </section>
        )
      })}

      <TaskDetails
        task={selected}
        practiceProgress={plan.chapters.find(chapter => chapter.id === selected?.chapterId)?.practice_progress}
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

function ChapterReview({
  chapter,
  task,
  courseId,
}: {
  chapter: Chapter
  task?: Task
  courseId: string
}) {
  const isDemo = courseId === 'demo'
  const timing = task?.date ? prettyDate(task.date) : 'Replan to schedule this review'

  return (
    <article className="plan-task">
      <span className="task-symbol review" aria-hidden="true">
        <RotateCcw size={17} strokeWidth={1.5} />
      </span>
      <div className="plan-task-body">
        {task ? (
          <Link
            className="task-title"
            href={`/courses/${courseId}/plan?task=${encodeURIComponent(task.id)}`}
          >
            {task.title}
          </Link>
        ) : (
          <span className="task-title">Review: {chapter.title}</span>
        )}
        {task && (task.date || (!isDemo && task.status !== 'Completed')) && (
          <p className="muted small">
            {timing}
            {!!task.schedule?.length && ` · ${task.estimated_minutes} min across ${task.schedule.length} day(s)`}
          </p>
        )}
      </div>
      {!isDemo && (
        <div className="plan-task-actions plan-review-actions">
          <Link className="button small secondary" href={`/courses/${courseId}/chapters/${chapter.id}/reports`}>
            Reports
          </Link>
        </div>
      )}
    </article>
  )
}

function taskStatusLabel(task: Task) {
  if (task.status === 'Completed') {
    if (task.completion_source === 'exam_pass') {
      return 'Completed by exam'
    }
    if (task.completion_source === 'practice_submit') {
      return 'Completed by practice'
    }
    return 'Completed'
  }

  return task.status === 'In progress'
    ? 'In progress'
    : 'Not started'
}

function chapterStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    planned: 'Planned',
    learning: 'Learning',
    learned: 'Learned',
    practice_in_progress: 'Practice in progress',
    exam_pending: 'Awaiting exam',
    completed: 'Chapter completed',
  }

  return labels[status || 'planned'] || 'Planned'
}

function reviewStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    not_assessed: 'Review after exam',
    required: 'Review required',
    passed: 'Exam passed',
  }

  return labels[status || 'not_assessed'] || 'Review after exam'
}
