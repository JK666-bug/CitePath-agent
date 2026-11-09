import { useState } from 'react'

import {
  Link,
  navigate,
  useLocation,
} from '../../shared/router'
import { messageOf } from '../../shared/request'
import { useStudy } from '../../shared/StudyProvider'
import {
  DemoNotice,
  Empty,
  Loading,
  Notice,
  PageHeader,
} from '../../shared/components/UI'

import { createPractice } from './api'

import './practice.css'

export default function PracticePage() {
  const { demo, courses, plans } = useStudy()
  const { search } = useLocation()
  const [startingId, setStartingId] = useState('')
  const [error, setError] = useState('')

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
        subtitle="Check your understanding, review weak concepts, and return to your plan."
        actions={
          <label>
            <span className="sr-only">
              Filter practice by course
            </span>

            <select
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
          {error && <Notice tone="error">{error}</Notice>}
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
                          disabled={startingId === `${course.id}-${chapter.id}`}
                          onClick={() => {
                            setError('')
                            setStartingId(`${course.id}-${chapter.id}`)
                            void createPractice(course.id, Number(chapter.id))
                              .then((created) =>
                                navigate(
                                  `/practice/${course.id}/sessions/${created.id}`,
                                ),
                              )
                              .catch((reason) => {
                                setError(messageOf(reason))
                                setStartingId('')
                              })
                          }}
                        >
                          {startingId === `${course.id}-${chapter.id}`
                            ? 'Opening…'
                            : 'Practice'}
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
    </div>
  )
}