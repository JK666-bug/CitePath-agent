import { useEffect, useMemo, useState } from 'react'

import {
  Link,
  useLocation,
} from '../../shared/router'
import {
  useCourse,
  useStudy,
} from '../../shared/StudyProvider'
import {
  Empty,
  Loading,
  Notice,
  PageHeader,
} from '../../shared/components/UI'

import { documentFileUrl } from './api'
import StudyTimeLog from './StudyTimeLog'

import './course.css'

export default function CourseReading({
  courseId,
}: {
  courseId: string
}) {
  const { search } = useLocation()
  const taskId = search.get('task') || ''
  const {
    course,
    error,
    retry,
    isDemo,
  } = useCourse(courseId)
  const {
    plans,
    loadPlan,
    finishPlanTask,
  } = useStudy()
  const numericId = Number(courseId)
  const plan = isDemo ? null : plans[numericId]?.plan
  const planLoaded = isDemo || Boolean(plans[numericId]?.loaded)

  useEffect(() => {
    if (!isDemo && Number.isFinite(numericId) && numericId > 0) {
      void loadPlan(numericId)
    }
  }, [isDemo, loadPlan, numericId])

  const task = plan?.tasks.find((item) => item.id === taskId) ?? null
  const sources = task?.sources ?? []
  const uniqueDocs = useMemo(() => {
    const seen = new Set<number>()
    const rows: {
      document_id: number
      filename: string
      page_number: number
      has_file: boolean
    }[] = []
    for (const source of sources) {
      if (seen.has(source.document_id)) continue
      seen.add(source.document_id)
      const material = course?.documents.find(
        (item) => item.id === source.document_id,
      )
      rows.push({
        document_id: source.document_id,
        filename: source.filename,
        page_number: source.page_number,
        has_file: Boolean(material?.has_file),
      })
    }
    return rows
  }, [sources, course])

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const activeId =
    selectedId ??
    uniqueDocs.find((item) => item.has_file)?.document_id ??
    uniqueDocs[0]?.document_id ??
    null
  const active = uniqueDocs.find((item) => item.document_id === activeId) ?? null

  if (error) {
    return (
      <Notice tone="error">
        {error}{' '}
        <button className="text-button" onClick={retry}>
          Try again
        </button>
      </Notice>
    )
  }

  if (!course || !planLoaded) {
    return <Loading text="Loading reading…" />
  }

  if (isDemo) {
    return (
      <div className="stack">
        <PageHeader
          eyebrow="Reading"
          title="Sample reading"
          subtitle="Demo courses do not include real PDF files."
        />
        <Empty title="No PDF to open">
          <Link href={`/courses/${courseId}/plan`}>Back to plan</Link>
        </Empty>
      </div>
    )
  }

  if (!task || task.kind !== 'Reading') {
    return (
      <div className="stack">
        <PageHeader eyebrow="Reading" title="Reading" />
        <Empty title="Reading task not found">
          <Link href={`/courses/${courseId}/plan`}>Back to plan</Link>
        </Empty>
      </div>
    )
  }

  return (
    <div className="course-reading stack">
      <PageHeader
        eyebrow="Chapter reading"
        title={task.title.replace(/^Read:\s*/i, '') || task.title}
        subtitle="Open the original lecture PDF for this reading step."
        actions={
          <>
            <button
              className="button"
              disabled={task?.status === 'Completed'}
              onClick={() => {
                if (task) {
                  void finishPlanTask(numericId, task.id)
                }
              }}
            >
              {task?.status === 'Completed' ? 'Completed' : 'Mark done'}
            </button>
            <Link
              className="button secondary"
              href={`/courses/${courseId}/plan`}
            >
              Back to plan
            </Link>
          </>
        }
      />

      {task.status === 'Completed' && <StudyTimeLog key={task.id} courseId={numericId} task={task} />}

      {!uniqueDocs.length ? (
        <Empty title="No PDF sources on this task">
          <Link href={`/courses/${courseId}/plan`}>Back to plan</Link>
        </Empty>
      ) : (
        <div className="reading-layout">
          <aside className="panel reading-files">
            <h2>Materials</h2>
            <ul className="reading-file-list">
              {uniqueDocs.map((item) => (
                <li key={item.document_id}>
                  <button
                    type="button"
                    className={
                      item.document_id === activeId
                        ? 'reading-file is-selected'
                        : 'reading-file'
                    }
                    onClick={() => setSelectedId(item.document_id)}
                  >
                    <strong title={item.filename}>{item.filename}</strong>
                    <span className="muted small">
                      Starts at page {item.page_number}
                      {!item.has_file ? ' · File missing' : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <section className="panel reading-viewer">
            {!active ? (
              <p className="muted">Select a PDF.</p>
            ) : !active.has_file ? (
              <Notice>
                Original PDF is not stored for {active.filename}. Re-upload
                it on{' '}
                <Link href={`/courses/${courseId}/info`}>
                  Course information
                </Link>{' '}
                to enable reading.
              </Notice>
            ) : (
              <iframe
                title={active.filename}
                className="reading-frame"
                src={
                  documentFileUrl(numericId, active.document_id) +
                  `#page=${active.page_number}`
                }
              />
            )}
          </section>
        </div>
      )}
    </div>
  )
}
