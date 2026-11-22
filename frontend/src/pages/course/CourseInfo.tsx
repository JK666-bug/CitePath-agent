import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { FileText } from 'lucide-react'
import ChapterRebuild from './ChapterRebuild'
import SchedulePanel from './SchedulePanel'
import { Link, useLocation } from '../../shared/router'
import { getCourseWorkflow, hasUnappliedSettings, scheduleReviewHref, scheduleStrategies, studyWeekdays } from './scheduleActions'
import type { Workflow } from './scheduleActions'
import { analyzeNewDocuments } from './chapterActions'
import ImportantDates from '../courseEditor/ImportantDates'
import { updateNoteDates } from '../courseEditor/noteCalendar'
import StudyDates from '../courseEditor/StudyDates'
import { addDays, dateKey, prettyDate } from '../../shared/format'
import { messageOf, request } from '../../shared/request'

import type {
  CourseDetail,
  Material,
  StudyPlan,
} from './types'

import { decodeBrief } from '../courseEditor/brief'

import MaterialPicker, {
  fileKey,
} from '../courseEditor/MaterialPicker'

import {
  deleteMaterial,
  duplicateMessage,
  uploadMaterial,
} from './api'

import { useStudy } from '../../shared/StudyProvider'

import {
  Modal,
  Notice,
} from '../../shared/components/UI'

type ScheduleProfile = NonNullable<StudyPlan['scheduling_profile']>

function scheduleSummary(profile: Partial<ScheduleProfile> | undefined) {
  if (!profile?.daily_minutes) return ''
  const order = scheduleStrategies.find(item => item.value === profile.strategy)?.label
  const days = profile.weekdays?.map(index => studyWeekdays[index]).join(', ')
  const period = profile.start && profile.end
    ? `${prettyDate(profile.start, true)} – ${prettyDate(profile.end, true)}`
    : ''
  const skips = profile.off_dates?.length
  const priorities = profile.priority_chapter_ids?.length
  return [
    `${profile.daily_minutes} min per study day`, days, order, period,
    skips ? `${skips} ${skips === 1 ? 'day' : 'days'} off` : '',
    priorities ? `${priorities} priority ${priorities === 1 ? 'chapter' : 'chapters'}` : '',
  ].filter(Boolean).join(' · ')
}

function materialStatus(material: Material, state: Workflow['documents'][number]['state'] | undefined) {
  if (material.ingest_status === 'pending') return 'Processing PDF'
  if (material.ingest_status !== 'complete') return 'PDF unavailable'
  if (!material.usable_page_count) return 'No readable pages'
  if (state === 'locked') return 'Learning started'
  if (state === 'planned') return 'Chapters ready'
  if (state === 'unplanned') return 'Awaiting chapter analysis'
  return 'PDF processed'
}

export default function CourseInfo({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const {
    loadCourse,
    refreshCourses,
    plans,
    loadPlan,
  } = useStudy()

  const config =
    decodeBrief(course.student_brief)

  const { search } = useLocation()
  const [editing, setEditing] = useState(search.get('edit') === 'schedule')
  const [name, setName] = useState(course.name)
  const [note, setNote] = useState(config.note)
  const [events, setEvents] = useState(config.events || [])
  const [dates, setDates] = useState({ startDate: config.startDate || dateKey(), deadline: config.deadline, earlyDays: config.earlyDays })
  const plan = plans[course.id]?.plan
  const hasChapters = Boolean(plan?.chapters.length)
  const hasRemainingTasks = Boolean(plan?.tasks.some(task => task.status !== 'Completed'))
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const publishedProfile = plan?.schedule_run_id ? plan.scheduling_profile : undefined
  const savedProfile = config.scheduling_profile
  const savedPreferences = scheduleSummary(savedProfile)
  const preferencesChanged = hasUnappliedSettings(config, plan)
  const canReview = Boolean(config.deadline && (publishedProfile || savedProfile))
  const reviewHref = scheduleReviewHref(course.id)
  const courseNameInput = useRef<HTMLInputElement>(null)
  useEffect(() => { if (courseId !== 'demo') void loadPlan(course.id) }, [course.id, courseId, loadPlan])
  useEffect(() => {
    if (courseId === 'demo') return
    let active = true
    void getCourseWorkflow(course.id).then(value => {
      if (active) setWorkflow(value)
    }).catch(() => {
      if (active) setWorkflow(null)
    })
    return () => { active = false }
  }, [course.id, course.documents, courseId, plan])

  function changeNote(next: string) {
    setEvents(current => updateNoteDates(next, current, dates, dateKey(), note))
    setNote(next)
  }

  async function saveInfo() {
    if (!name.trim() || events.some(x => !x.title.trim() || !x.date)) {
      setError('Enter a course name and a title and full date for every event.'); return
    }
    if (!dates.startDate || dates.startDate < dateKey() || !dates.deadline || !Number.isInteger(dates.earlyDays) || dates.earlyDays < 0 || dates.earlyDays > 365 || addDays(dates.deadline, -dates.earlyDays) < dates.startDate) {
      setError('Choose a valid start date and planned finish date on or after the start date.'); return
    }
    setBusy(true); setError('')
    try {
      await request(`/api/courses/${course.id}/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, note, events, startDate: dates.startDate, deadline: dates.deadline, earlyDays: dates.earlyDays }) })
      await reload()
      setMessage('Course information saved. Use the daily schedule below to regenerate this course’s plan.')
    } catch (reason) { setError(messageOf(reason)) } finally { setBusy(false) }
  }

  const demo = courseId === 'demo'

  const [files, setFiles] =
    useState<File[]>([])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] =
    useState('')

  const [remove, setRemove] =
    useState<Material | null>(null)

  const [replanPrompt, setReplanPrompt] = useState<'upload' | 'rebuild' | null>(null)

  function editSettings() {
    if (!editing) {
      setName(course.name)
      setNote(config.note)
      setEvents(config.events || [])
      setDates({ startDate: config.startDate || dateKey(), deadline: config.deadline, earlyDays: config.earlyDays })
      setEditing(true)
    }
    setReplanPrompt(null)
    requestAnimationFrame(() => courseNameInput.current?.focus())
  }

  async function reload() {
    await Promise.all([loadCourse(course.id), refreshCourses()])
  }

  async function refreshChapters() {
    const [, result] = await Promise.all([reload(), loadPlan(course.id)])
    if (!result) throw new Error('Could not refresh the chapter list. Reload the page to see your saved changes.')
    return result.plan
  }

  async function upload(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (busy || demo) return

    setError('')
    setMessage('')

    if (
      !files.length ||
      files.some(
        (file) =>
          !file.name
            .toLowerCase()
            .endsWith('.pdf') ||
          !file.size,
      )
    ) {
      setError(
        'Choose one or more non-empty PDF files.',
      )
      return
    }

    setBusy(true)
    const messages: string[] = []
    let changesSaved = false

    try {
      for (const file of files) {
        setMessage(`Uploading and processing ${file.name}…`)
        const result = await uploadMaterial(course.id, file)
        changesSaved = true
        if (result.duplicate) {
          messages.push(duplicateMessage(file.name, result.filename))
        }
        if (!result.usable_page_count) messages.push(`${file.name} has no readable pages for chapter analysis.`)
        setFiles(current => current.filter(item => fileKey(item) !== fileKey(file)))
      }

      setMessage('Analyzing uploaded PDFs into chapters…')
      const analyzed = await analyzeNewDocuments(course.id)
      const updatedPlan = await refreshChapters()
      setMessage(messages.join(' ') || (analyzed ? '' : 'These materials are already up to date.'))
      if (analyzed && updatedPlan?.chapters.length) setReplanPrompt('upload')
    } catch (reason) {
      setMessage('')
      setError(changesSaved
        ? `${messageOf(reason)} Saved PDFs remain in this course. Check Course materials or use Rebuild chapters to finish analysis.`
        : messageOf(reason))
      await Promise.allSettled([reload(), loadPlan(course.id)])
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (!remove || busy || demo) return

    setBusy(true)
    setError('')
    setMessage('')
    let deleted = false

    try {
      await deleteMaterial(course.id, remove.id)
      deleted = true
      setRemove(null)
      const updatedPlan = await refreshChapters()
      setMessage(updatedPlan?.chapters.length
        ? 'Material removed. The plan and priority chapters are up to date.'
        : 'Material removed. Upload a PDF to create new chapters.')
    } catch (reason) {
      setRemove(null)
      setError(messageOf(reason))
      if (deleted) setMessage('The material was removed.')
      await Promise.allSettled([reload(), loadPlan(course.id)])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <section className="panel">
        <div className="actions">
          <h2>Course settings</h2>
          {!demo && (
            <button
              className="button small secondary"
              type="button"
              disabled={busy}
              onClick={() => editing ? setEditing(false) : editSettings()}
            >
              {editing ? 'Cancel' : 'Edit'}
            </button>
          )}
        </div>
        {editing ? <div className="stack">
          <label className="field"><span>Course name *</span><input ref={courseNameInput} value={name} onChange={e => setName(e.target.value)} maxLength={255} /></label>
          <label className="field"><span>Course note and calendar dates</span><textarea value={note} onChange={e => changeNote(e.target.value)} maxLength={9000} /></label>
          <ImportantDates
            value={events}
            onChange={setEvents}
            onFind={note.trim() && note === config.note
              ? () => setEvents(current => updateNoteDates(note, current, dates, dateKey()))
              : undefined}
          />
          {!hasChapters && <><StudyDates value={dates} onChange={next => setDates({ ...next, startDate: next.startDate || '' })} /><button className="button secondary" disabled={busy} onClick={() => void saveInfo()}>Save course information</button><p className="muted small">Analyze a PDF to enable daily scheduling.</p></>}
          {hasChapters && plan && <SchedulePanel course={course} plan={plan} courseSettings={{ name, note, events }} courseWorkflow={workflow} inline onSaved={() => {
            setEditing(false)
            setMessage('Study settings saved.')
          }} />}
        </div> : <>
          <dl className="course-facts"><div><dt>Course name</dt><dd>{course.name}</dd></div><div><dt>Start learning on</dt><dd>{config.startDate ? prettyDate(config.startDate, true) : plan?.scheduling_profile?.start ? prettyDate(plan.scheduling_profile.start, true) : 'Not set'}</dd></div><div><dt>Learning deadline</dt><dd>{config.deadline ? prettyDate(config.deadline, true) : 'Not set'}</dd></div><div><dt>Finish early by</dt><dd>{config.earlyDays} days</dd></div><div><dt>Materials</dt><dd>{course.documents.length} PDFs</dd></div></dl>
          <h3>Course note and calendar dates</h3><p className="course-note">{config.note || 'No additional note.'}</p>
          {config.events?.length ? <ul>{config.events.map((item, i) => <li key={i}>{item.date} · {item.title}</li>)}</ul> : <p className="muted small">No calendar dates added.</p>}
          <h3>Daily learning schedule</h3>
          <dl className="course-schedule-summary">
            <div>
              <dt>Saved preferences</dt>
              <dd>{savedPreferences || 'No scheduling preferences saved yet.'}</dd>
              {preferencesChanged && <dd>Your calendar still uses the previous settings. Review the schedule to apply these changes.</dd>}
            </div>
          </dl>
          {hasChapters && !hasRemainingTasks && <p className="muted small">All tasks completed.</p>}
          {!demo && hasRemainingTasks && (canReview
            ? <Link className="button small secondary" href={reviewHref}>Review schedule</Link>
            : <button type="button" className="button small secondary" disabled={busy} onClick={editSettings}>Set up daily schedule</button>
          )}
        </>}
      </section>

      {error && (
        <Notice tone="error">
          {error}
        </Notice>
      )}

      {message && (
        <Notice>{message}</Notice>
      )}

      <section className="panel">
        <h2>Course materials</h2>

        {course.documents.length ? (
          <ul className="materials-list">
            {course.documents.map(
              (material) => (
                <li key={material.id}>
                  <FileText
                    size={18}
                    strokeWidth={1.4}
                  />

                  <div>
                    <strong>
                      {material.filename}
                    </strong>

                    <p>
                      Doc {material.position}
                      {' · '}
                      {material.page_count}
                      {' '}pages
                      {' · '}
                      {material.usable_page_count}
                      {' '}usable pages
                    </p>
                  </div>

                  <span className="badge">
                    {materialStatus(material, workflow?.documents.find(document => document.id === material.id)?.state)}
                  </span>

                  <button
                    className="button small danger"
                    disabled={busy || demo}
                    onClick={() =>
                      setRemove(material)
                    }
                  >
                    Delete
                  </button>
                </li>
              ),
            )}
          </ul>
        ) : (
          <p className="muted">
            No materials uploaded yet.
          </p>
        )}

        {demo ? (
          <p className="muted small">
            Sample PDF references are
            illustrative. This demo does not
            contain real PDF files.
          </p>
        ) : (
          <form
            className="stack"
            onSubmit={upload}
            noValidate
          >
            <MaterialPicker
              files={files}
              onChange={setFiles}
              disabled={busy}
            />

            <div className="actions">
              <button
                className="button"
                disabled={
                  busy || !files.length
                }
              >
                {busy
                  ? 'Processing materials…'
                  : 'Upload materials'}
              </button>


            </div>
          </form>
        )}
      </section>

      {!demo && <ChapterRebuild courseId={course.id} disabled={busy} onRebuilt={() => setReplanPrompt('rebuild')} />}
      <Modal
        open={replanPrompt !== null}
        title="Chapters are ready"
        onClose={() => setReplanPrompt(null)}
      >
        <div className="stack">
          <p>
            {replanPrompt === 'upload'
              ? 'Your new chapters are available in Plan. '
              : 'Your updated chapters are available in Plan. '}
            Review a new schedule to place unfinished tasks on your calendar.
          </p>
          <div className="actions">
            {canReview && hasRemainingTasks && <Link className="button" href={reviewHref}>Review schedule</Link>}
            <button type="button" className="button secondary" disabled={busy} onClick={editSettings}>
              Edit study settings
            </button>
          </div>
        </div>
      </Modal>
      <Modal
        open={Boolean(remove)}
        title="Delete course material?"
        closeable={!busy}
        onClose={() => setRemove(null)}
      >
        <p>
          Delete {remove?.filename}? Chapters that use only this PDF and their tasks will be removed from the active plan.
          Past study records will stay in your history.
        </p>

        <div className="actions">
          <button
            className="button danger"
            disabled={busy}
            onClick={confirmDelete}
          >
            {busy
              ? 'Deleting…'
              : 'Delete material'}
          </button>

          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setRemove(null)}
          >
            Cancel
          </button>
        </div>
      </Modal>
    </div>
  )
}
