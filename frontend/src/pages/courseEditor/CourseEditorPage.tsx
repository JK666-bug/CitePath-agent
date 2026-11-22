import { useRef, useState } from 'react'
import type { FormEvent } from 'react'

import {
  useCourse,
  useStudy,
} from '../../shared/StudyProvider'

import { Link } from '../../shared/router'
import { addDays, dateKey } from '../../shared/format'

import {
  ApiError,
  messageOf,
} from '../../shared/request'


import {
  DemoNotice,
  Loading,
  Notice,
  PageHeader,
} from '../../shared/components/UI'

import type { CourseDetail } from '../course/types'
import {
  duplicateMessage,
  uploadMaterial,
} from '../course/api'

import { createCourse } from './api'

import {
  decodeBrief,
  encodeBrief,
} from './brief'

import ImportantDates from './ImportantDates'
import { updateNoteDates } from './noteCalendar'
import { analyzeNewDocuments } from '../course/chapterActions'
import SchedulePanel from '../course/SchedulePanel'
import CourseForm from './CourseForm'
import type { CourseFormValue } from './CourseForm'

import MaterialPicker, {
  fileKey,
} from './MaterialPicker'

import AnalysisDialog from './AnalysisDialog'
import './courseEditor.css'

function Editor({
  course,
  courseId,
}: {
  course?: CourseDetail
  courseId?: string
}) {
  const isDemo = courseId === 'demo'
  const realEdit =
    Boolean(course && !isDemo)

  const {
    editDemo,
    refreshCourses,
    loadCourse,
    loadPlan,
    plans,
  } = useStudy()

  const [value, setValue] =
    useState<CourseFormValue>(() => ({
      name: course?.name || '',
      ...(course
        ? decodeBrief(
            course.student_brief,
          )
        : {
            startDate: dateKey(),
            deadline: '',
            earlyDays: 0,
            events: [],
            note: '',
          }),
    }))

  const [files, setFiles] =
    useState<File[]>([])

  const [errors, setErrors] =
    useState<Record<string, string>>({})

  const [busy, setBusy] = useState(false)
  const [creationComplete, setCreationComplete] = useState(false)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const scheduleSection = useRef<HTMLDivElement>(null)

  const [createdId, setCreatedId] =
    useState<number | null>(null)

  const [uploaded, setUploaded] =
    useState<string[]>([])

  const [
    uncertainCreate,
    setUncertainCreate,
  ] = useState(false)

  const [retryChecked, setRetryChecked] =
    useState(false)

  async function save(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (
      busy ||
      creationComplete ||
      realEdit ||
      uncertainCreate
    ) {
      return
    }

    const next: Record<string, string> = {}

    if (!value.name.trim()) {
      next.name =
        'Please enter a course name.'
    }

    if (!value.startDate || value.startDate < dateKey()) next.startDate = 'Choose today or a future start date.'
    if (!value.deadline || value.deadline < dateKey()) next.deadline = 'Choose today or a future date.'
    if (!Number.isInteger(value.earlyDays) || value.earlyDays < 0 || value.earlyDays > 365 || (value.deadline && value.startDate && addDays(value.deadline, -value.earlyDays) < value.startDate)) next.earlyDays = 'The planned finish must be on or after the start date.'

    if ((value.events || []).some((item) => !item.title.trim() || !item.date)) {
      next.note = 'Give every important date a title and full date, or remove the incomplete row.'
    }

    if (!files.length && !createdId && !isDemo) {
      next.files = 'Choose at least one PDF to analyze.'
    }

    if (
      files.some(
        (file) =>
          !file.name
            .toLowerCase()
            .endsWith('.pdf'),
      )
    ) {
      next.files =
        'Please choose PDF files only.'
    }

    if (
      files.some(
        (file) => file.size === 0,
      )
    ) {
      next.files =
        'Empty files cannot be uploaded.'
    }

    const brief = encodeBrief({
      startDate: value.startDate,
      deadline: value.deadline,
      earlyDays: value.earlyDays,
      note: value.note,
      events: value.events || [],
    })

    if (
      Array.from(brief).length > 10000
    ) {
      next.note =
        'Your course settings and note are too long. Please shorten your note.'
    }

    setErrors(next)

    if (Object.keys(next).length) {
      document
        .getElementById(
          `course-${Object.keys(next)[0]}`,
        )
        ?.focus()

      return
    }

    setBusy(true)
    setOpen(true)
    setError('')
    setStatus('Saving course settings…')

    let id = createdId

    try {
      if (isDemo) {
        editDemo(
          value.name.trim(),
          value,
        )

        setStatus(
          'Sample study time and dates have been recalculated.',
        )
      } else {
        if (!id) {
          const result =
            await createCourse(
              value.name.trim(),
              brief,
            )

          id = result.id
          setCreatedId(id)
        }

        const duplicates: string[] = []
        let newUploads = 0

        for (const file of files) {
          if (
            uploaded.includes(
              fileKey(file),
            )
          ) {
            continue
          }

          setStatus(
            `Uploading and processing ${file.name}…`,
          )

          const result =
            await uploadMaterial(id, file)

          if (!result.duplicate) newUploads += 1
          if (result.duplicate) {
            duplicates.push(
              duplicateMessage(
                file.name,
                result.filename,
              ),
            )
          }

          setUploaded((current) => [
            ...current,
            fileKey(file),
          ])
        }

        setStatus('Analyzing new materials into chapters…')
        const analyzed = await analyzeNewDocuments(id)
        if (newUploads && !analyzed) throw new Error('PDFs were saved but are not ready for chapter analysis. Check Course info and try again.')
        await Promise.all([loadCourse(id), loadPlan(id), refreshCourses()])
        setCreationComplete(true)

        setStatus(
          duplicates.length
            ? duplicates.join(' ')
            : 'Your materials have been processed.',
        )
      }
    } catch (reason) {
      if (
        !id &&
        reason instanceof ApiError &&
        (
          reason.status === 0 ||
          reason.status >= 500
        )
      ) {
        setUncertainCreate(true)
      }

      setRetryChecked(false)

      setError(
        `${messageOf(reason)} A request may have reached the server. Check My courses and saved materials before retrying.`,
      )

      setStatus(
        id
          ? 'The course already exists. Do not create it again.'
          : 'Please verify whether a course was created before starting another request.',
      )

      await refreshCourses()
    } finally {
      setBusy(false)
    }
  }

  const planEntry = createdId ? plans[createdId] : undefined
  const createdPlan = planEntry?.plan
  const scheduleReady = Boolean(creationComplete && createdPlan?.chapters.length)
  const remainingUploads = files.some(file => !uploaded.includes(fileKey(file)))

  function continueToSchedule() {
    setOpen(false)
    requestAnimationFrame(() => {
      scheduleSection.current?.focus({ preventScroll: true })
      scheduleSection.current?.scrollIntoView({ block: 'start' })
    })
  }

  const retryBlocked = Boolean(
    createdId &&
    error &&
    !retryChecked,
  )

  return (
    <div className="course-editor-page">
      <PageHeader
        eyebrow={creationComplete ? 'Course saved' : course ? 'Course settings' : 'A new learning path'}
        title={creationComplete ? value.name.trim() : course ? 'Edit course' : 'Create a course'}
        subtitle={creationComplete ? undefined : 'Keep your materials and study dates together.'}
        actions={!creationComplete && (
          <Link className="button secondary" href={courseId ? `/courses/${courseId}/info` : '/courses'}>Back</Link>
        )}
      />

      {isDemo && <DemoNotice />}

      {realEdit && (
        <Notice>
          The current backend supports reading
          course settings but has no update
          endpoint. These settings are
          read-only here. You can manage PDF
          materials in Course information.
        </Notice>
      )}

      {!creationComplete && <form
        className="panel editor-form stack"
        noValidate
        onSubmit={save}
      >
        <CourseForm
          value={value}
          onChange={(next) => {
            setValue(current => ({
              ...next,
              events: next.note === current.note
                ? current.events
                : updateNoteDates(next.note, current.events || [], next, dateKey(), current.note),
            }))
            setErrors({})
          }}
          errors={errors}
          disabled={
            busy ||
            realEdit ||
            createdId !== null
          }
        />

        <ImportantDates
          value={value.events || []}
          onChange={(events) => setValue(current => ({ ...current, events }))}
          disabled={busy || createdId !== null || realEdit}
        />
        <section>
          <h2>Course materials</h2>

          {course && (
            <p className="muted small">
              {course.documents.length}
              {' '}materials already saved.
              {' '}
              <Link
                href={
                  `/courses/${courseId}/info`
                }
              >
                View materials
              </Link>
            </p>
          )}

          {isDemo ? (
            <p className="muted">
              This demo uses fixed sample
              materials. Upload your own PDFs
              through a real course.
            </p>
          ) : (
            !realEdit && (
              <MaterialPicker
                files={files}
                onChange={setFiles}
                disabled={busy}
              />
            )
          )}

          {errors.files && (
            <p
              className="field-error"
              role="alert"
            >
              {errors.files}
            </p>
          )}
        </section>

        {error && (
          <Notice tone="error">
            {error}
          </Notice>
        )}

        {createdId && error && (
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={retryChecked}
              onChange={(event) =>
                setRetryChecked(
                  event.target.checked,
                )
              }
            />
            I checked which files were already saved.
          </label>
        )}

        {createdId && error && (
          <p className="muted small">
            Your course is saved.{' '}
            <Link href={`/courses/${createdId}/info`} target="_blank" rel="noreferrer">
              Check uploaded materials
            </Link>
          </p>
        )}

        {uncertainCreate && (
          <Notice>
            <Link href="/courses">
              Check My courses before starting
              a new request.
            </Link>
          </Notice>
        )}

        <div className="actions">
          <button
            className="button"
            type="submit"
            disabled={
              busy ||
              realEdit ||
              uncertainCreate ||
              retryBlocked
            }
          >
            {busy
              ? 'Saving…'
              : isDemo
                ? 'Save and update sample plan'
                : createdId
                  ? remainingUploads ? 'Retry uploads' : 'Retry chapter analysis'
                  : 'Save course'}
          </button>
        </div>
      </form>}

      {creationComplete && createdId && !scheduleReady && (
        <div className="editor-form">
          {planEntry?.loading ? (
            <Loading text="Loading chapters…" />
          ) : planEntry?.error ? (
            <Notice tone="error">
              {planEntry.error}{' '}
              <button className="text-button" type="button" onClick={() => void loadPlan(createdId)}>Try again</button>
            </Notice>
          ) : (
            <Notice>
              Finish analyzing your PDFs in <Link href={`/courses/${createdId}/info`}>Course settings</Link> to enable daily scheduling.
            </Notice>
          )}
        </div>
      )}

      {createdId && createdPlan && scheduleReady && (
        <div className="editor-form" ref={scheduleSection} tabIndex={-1} role="region" aria-label="Daily learning schedule">
          <SchedulePanel
            course={{ id: createdId, name: value.name, student_brief: encodeBrief(value), created_at: '', documents: [] }}
            plan={createdPlan}
            hideStudyDates
          />
        </div>
      )}
      <AnalysisDialog
        open={open}
        busy={busy}
        status={status}
        error={error}
        demo={isDemo}
        courseId={
          createdId
            ? String(createdId)
            : courseId || ''
        }
        onClose={() => setOpen(false)}
        onSchedule={scheduleReady ? continueToSchedule : undefined}
      />
    </div>
  )
}

function ExistingEditor({
  courseId,
}: {
  courseId: string
}) {
  const {
    course,
    error,
    retry,
  } = useCourse(courseId)

  if (error) {
    return (
      <Notice tone="error">
        {error}{' '}
        <button
          className="text-button"
          onClick={retry}
        >
          Try again
        </button>
      </Notice>
    )
  }

  if (!course) {
    return (
      <Loading text="Loading course settings…" />
    )
  }

  return (
    <Editor
      course={course}
      courseId={courseId}
    />
  )
}

export default function CourseEditorPage({
  courseId,
}: {
  courseId?: string
}) {
  return courseId ? (
    <ExistingEditor courseId={courseId} />
  ) : (
    <Editor />
  )
}
