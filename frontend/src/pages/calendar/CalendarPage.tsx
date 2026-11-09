import {
  useEffect,
  useState,
} from 'react'

import {
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'

import { useStudy } from '../../shared/StudyProvider'

import {
  Link,
  navigate,
  useLocation,
} from '../../shared/router'

import {
  dateKey,
  parseDate,
} from '../../shared/format'

import {
  DemoNotice,
  Notice,
  PageHeader,
} from '../../shared/components/UI'

import PaceLine, {
  ProgressTrack,
  taskTotals,
} from '../../shared/components/PaceLine'

import { decodeBrief } from '../courseEditor/brief'
import type { CalendarTask } from '../course/types'

import MonthGrid from './MonthGrid'
import DayOverview from './DayOverview'

import './calendar.css'

function validDate(
  value: string | null,
) {
  if (
    !value ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value)
  ) {
    return ''
  }

  return dateKey(parseDate(value)) === value
    ? value
    : ''
}

export default function CalendarPage() {
  const {
    demo,
    courses,
    completeTask,
    plans,
    loadPlan,
    finishPlanTask,
  } = useStudy()

  const { search } = useLocation()

  const selected =
    validDate(search.get('date'))

  const filter =
    search.get('course') || 'all'

  const demoMode = filter === 'demo'

  useEffect(() => {
    for (const course of courses) {
      void loadPlan(course.id)
    }
  }, [courses, loadPlan])

  const [month, setMonth] = useState(
    () =>
      selected
        ? parseDate(selected)
        : new Date(),
  )

  useEffect(() => {
    if (selected) {
      setMonth(parseDate(selected))
    }
  }, [selected])

  const selectedCourse = courses.find(
    (course) =>
      String(course.id) === filter,
  )

  const demoTasks: CalendarTask[] =
    demo.plan.tasks.map((task) => ({
      ...task,
      courseId: 'demo',
      courseName: demo.course.name,
    }))

  const realTasks: CalendarTask[] =
    courses.flatMap((course) => {
      if (
        filter !== 'all' &&
        String(course.id) !== filter
      ) {
        return []
      }

      const plan = plans[course.id]?.plan

      if (!plan) {
        return []
      }

      return plan.tasks.map((task) => ({
        ...task,
        courseId: String(course.id),
        courseName: course.name,
      }))
    })

  const tasks = demoMode
    ? demoTasks
    : realTasks

  const outlookPlan = demoMode
    ? demo.plan
    : selectedCourse
      ? plans[selectedCourse.id]?.plan
      : null

  const outlookConfig = demoMode
    ? decodeBrief(demo.course.student_brief)
    : selectedCourse
      ? decodeBrief(selectedCourse.student_brief)
      : null

  const todayTasks = tasks.filter(
    (task) =>
      task.date === dateKey(),
  )

  const todayTotals =
    taskTotals(todayTasks)

  function update(values: {
    date?: string
    course?: string
  }) {
    const next =
      new URLSearchParams(search)

    for (
      const [key, value]
      of Object.entries(values)
    ) {
      if (value) {
        next.set(key, value)
      } else {
        next.delete(key)
      }
    }

    navigate(
      `/calendar${
        next.size ? `?${next}` : ''
      }`,
    )
  }

  return (
    <div className="calendar-page">
      <PageHeader
        eyebrow="One day at a time"
        title="Study calendar"
        subtitle="Reading, practice, and review in one clear view."
      />

      {demoMode ? (
        <DemoNotice />
      ) : (
        !tasks.length && (
          <Notice>
            Generate a study plan from a course
            to see it here.{' '}
            <Link
              href={
                selectedCourse
                  ? `/courses/${selectedCourse.id}/plan`
                  : '/courses'
              }
            >
              Open a course plan
            </Link>
            .
          </Notice>
        )
      )}

      <div className="calendar-progress">
        <section className="panel">
          <ProgressTrack
            label="Today’s study pace"
            unavailable={!tasks.length}
            done={todayTotals.done}
            total={todayTotals.total}
          />

          {tasks.length ? (
            <small className="muted">
              Target: complete today’s
              scheduled tasks.
            </small>
          ) : (
            <small className="muted">
              No tasks scheduled yet.
            </small>
          )}
        </section>

        <section className="panel">
          <h2 className="calendar-pace-title">
            Overall schedule outlook
          </h2>

          {outlookPlan && outlookConfig ? (
            <PaceLine
              plan={outlookPlan}
              config={outlookConfig}
              compact
            />
          ) : (
            <ProgressTrack
              label="Overall study pace"
              unavailable={!tasks.length}
              done={taskTotals(tasks).done}
              total={taskTotals(tasks).total}
            />
          )}
        </section>
      </div>

      <section className="calendar-toolbar">
        <div className="actions">
          <button
            className="icon-button"
            aria-label="Previous month"
            onClick={() => {
              setMonth((current) =>
                new Date(
                  current.getFullYear(),
                  current.getMonth() - 1,
                  1,
                  12,
                ),
              )

              update({ date: '' })
            }}
          >
            <ChevronLeft size={17} />
          </button>

          <h2>
            {new Intl.DateTimeFormat(
              'en-US',
              {
                month: 'long',
                year: 'numeric',
              },
            ).format(month)}
          </h2>

          <button
            className="icon-button"
            aria-label="Next month"
            onClick={() => {
              setMonth((current) =>
                new Date(
                  current.getFullYear(),
                  current.getMonth() + 1,
                  1,
                  12,
                ),
              )

              update({ date: '' })
            }}
          >
            <ChevronRight size={17} />
          </button>

          <button
            className="button small secondary"
            onClick={() => {
              setMonth(new Date())
              update({ date: dateKey() })
            }}
          >
            Today
          </button>
        </div>

        <label className="calendar-filter">
          <span className="sr-only">
            Filter courses
          </span>

          <select
            className="cp-select"
            value={filter}
            onChange={(event) =>
              update({
                course:
                  event.target.value,
                date: '',
              })
            }
          >
            <option value="all">
              All real courses
            </option>

            {courses.map((course) => (
              <option
                key={course.id}
                value={String(course.id)}
              >
                {course.name}
              </option>
            ))}

            <option value="demo">
              Interface demo course
            </option>
          </select>
        </label>
      </section>

      <div
        className={
          `calendar-workspace ${
            selected
              ? 'has-overview'
              : ''
          }`
        }
      >
        <div className="calendar-board">
          <MonthGrid
            month={month}
            selected={selected}
            tasks={tasks}
            onSelect={(date) => {
              setMonth(parseDate(date))

              update({
                date:
                  selected === date
                    ? ''
                    : date,
              })
            }}
          />
        </div>

        {selected && (
          <DayOverview
            date={selected}
            tasks={tasks.filter(
              (task) =>
                task.date === selected,
            )}
            onClose={() =>
              update({ date: '' })
            }
            onComplete={(task) => {
              if (task.courseId === 'demo') {
                completeTask(task.id)
                return
              }

              void finishPlanTask(
                Number(task.courseId),
                task.id,
              )
            }}
          />
        )}
      </div>
    </div>
  )
}