import { useState } from 'react'

import {
  Link,
  navigate,
  useLocation,
} from '../../shared/router'
import { useStudy } from '../../shared/StudyProvider'
import {
  DemoNotice,
  Empty,
  Loading,
  PageHeader,
} from '../../shared/components/UI'

import PracticeStartModal from './PracticeStartModal'

import './practice.css'

export default function PracticePage() {
  const { demo, courses, plans } = useStudy()
  const { search } = useLocation()
  const [target, setTarget] = useState<{
    courseId: number
    chapterId: number
  } | null>(null)

  const filter =
    search.get('course') || 'all'
  const visibleCourses = courses.filter(
    (course) =>
      filter === 'all' ||
      String(course.id) === filter,
  )

  return (
    <div className="practice-page">
      <PageHeader
        eyebrow="Practice with evidence"
        title="Chapter practice"
        subtitle="Check your understanding and return to your plan."
        actions={
          <label>
            <span className="sr-only">
              Filter practice by course
            </span>

            <select
              aria-label="Filter practice by course"
              className="cp-select"
              value={filter}
              onChange={(event) =>
                navigate(
                  '/practice?course=' +
                    encodeURIComponent(
                      event.target.value,
                    ),
                )
              }
            >
              <option value="all">
                All real courses
              </option>

              {courses.map((course) => (
                <option
                  key={course.id}
                  value={course.id}
                >
                  {course.name}
                </option>
              ))}

              <option value="demo">
                Interface demo course
              </option>
            </select>
          </label>
        }
      />

      {filter === 'demo' ? (
        <>
          <DemoNotice />

          <div className="practice-grid">
            {demo.plan.chapters.map(
              (chapter, index) => {
                const session =
                  demo.sessions[chapter.id]

                const last =
                  session?.history.at(-1)

                return (
                  <article
                    key={chapter.id}
                    className="panel practice-chapter"
                  >
                    <p className="eyebrow">
                      Chapter {index + 1}
                      {' · '}
                      Interface demo
                    </p>

                    <h2>{chapter.title}</h2>

                    <p className="muted small">
                      {chapter.concepts.join(
                        ' · ',
                      )}
                    </p>

                    <div className="actions">
                      <span className="badge">
                        {session
                          ? session.status
                          : 'Not started'}
                      </span>

                      {session && (
                        <small className="muted">
                          Round {session.round}
                          {' / 2'}
                        </small>
                      )}
                    </div>

                    {last && (
                      <p className="chapter-score">
                        Last score
                        <strong>
                          {last.score}%
                        </strong>
                      </p>
                    )}

                    <div className="actions">
                      <Link
                        className="button small"
                        href={
                          `/practice/demo/${chapter.id}`
                        }
                      >
                        {!session
                          ? 'Start practice'
                          : session.status ===
                              'Answering'
                            ? 'Continue practice'
                            : 'View result'}
                      </Link>

                      {last && (
                        <Link
                          className="button small secondary"
                          href={
                            `/practice/demo/${chapter.id}/report`
                          }
                        >
                          View report
                        </Link>
                      )}
                    </div>
                  </article>
                )
              },
            )}
          </div>
        </>
      ) : (
        <div className="stack">
          {visibleCourses.length === 0 && (
            <Empty title="No courses yet">
              <Link href="/courses">Back to my courses</Link>
            </Empty>
          )}
          {visibleCourses.map((course) => {
            const entry = plans[course.id]
            if (!entry?.loaded) {
              return (
                <Loading
                  key={course.id}
                  text={`Loading ${course.name}…`}
                />
              )
            }
            const chapters = entry.plan?.chapters ?? []
            if (!chapters.length) {
              return (
                <Empty key={course.id} title={course.name}>
                  <p>Generate a study plan before practicing.</p>
                  <Link href={`/courses/${course.id}/plan`}>
                    Open plan
                  </Link>
                </Empty>
              )
            }
            return (
              <section className="stack" key={course.id}>
                <h2>{course.name}</h2>
                <div className="practice-grid">
                  {chapters.map((chapter, index) => (
                    <article
                      className="panel practice-chapter"
                      key={chapter.id}
                    >
                      <p className="eyebrow">
                        Chapter {index + 1}
                      </p>
                      <h2>{chapter.title}</h2>
                      <p className="muted small">
                        {chapter.concepts.join(' · ')}
                      </p>
                      <div className="actions">
                        <button
                          className="button small"
                          onClick={() =>
                            setTarget({
                              courseId: course.id,
                              chapterId: Number(chapter.id),
                            })
                          }
                        >
                          Practice
                        </button>
                        <Link
                          className="button small secondary"
                          href={`/courses/${course.id}/chapters/${chapter.id}/reports`}
                        >
                          View reports
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}

      <PracticeStartModal
        open={target != null}
        courseId={target?.courseId ?? 0}
        chapterId={target?.chapterId ?? null}
        onClose={() => setTarget(null)}
      />
    </div>
  )
}
