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
import ReadingTutor from './ReadingTutor'
import { sourcePageLabel } from './SourceSummary'

import './course.css'

function pageSpan(sources: { document_id: number; page_number: number }[], documentId: number) {
  const pages = sources
    .filter(source => source.document_id === documentId)
    .map(source => source.page_number)
    .sort((a, b) => a - b)
  if (!pages.length) return 'Pages not set'
  const start = pages[0]
  const end = pages[pages.length - 1]
  return start === end ? `Page ${start}` : `Pages ${start}–${end}`
}

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
      page_count?: number
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
        page_count: material?.page_count,
        has_file: Boolean(material?.has_file),
      })
    }
    return rows
  }, [sources, course])

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const active =
    uniqueDocs.find((item) => item.document_id === selectedId) ??
    uniqueDocs.find((item) => item.has_file) ??
    uniqueDocs[0] ??
    null
  const activeId = active?.document_id

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

  const title = task.title.replace(/^Read:\s*/i, '') || task.title
  const pagesLabel = sourcePageLabel(task.sources)

  return (
    <div className="reading-stage">
      <section className="reading-stage-pdf" aria-label="Lecture PDF">
        <header className="reading-stage-bar">
          <Link className="button small secondary" href={`/courses/${courseId}/plan`}>
            Back
          </Link>
          <div className="reading-stage-title">
            <strong>{title}</strong>
            {pagesLabel && <span className="muted small">{pagesLabel}</span>}
          </div>
          {uniqueDocs.length > 1 && (
            <div className="reading-doc-switch" aria-label="Reading PDFs">
              {uniqueDocs.map((item) => (
                <button
                  key={item.document_id}
                  type="button"
                  className={item.document_id === activeId ? 'is-selected' : ''}
                  onClick={() => setSelectedId(item.document_id)}
                >
                  {pageSpan(sources, item.document_id)}
                </button>
              ))}
            </div>
          )}
        </header>
        {!active ? (
          <Empty title="No PDF sources on this task">
            <Link href={`/courses/${courseId}/plan`}>Back to plan</Link>
          </Empty>
        ) : !active.has_file ? (
          <Notice>
            Original PDF is not stored for {active.filename}. Re-upload it on{' '}
            <Link href={`/courses/${courseId}/info`}>Course information</Link>{' '}
            to enable reading.
          </Notice>
        ) : (
          <iframe
            title={active.filename}
            className="reading-frame"
            src={`${documentFileUrl(numericId, active.document_id)}#page=${active.page_number}`}
          />
        )}
      </section>
      <ReadingTutor
        courseId={numericId}
        taskId={task.id}
        document={active}
      />
    </div>
  )
}
