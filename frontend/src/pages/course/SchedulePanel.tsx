import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowDown, ArrowUp, CalendarDays, CalendarX, ChevronDown, ListOrdered, Plus, X } from 'lucide-react'
import type { CourseDetail, StudyPlan } from './types'
import { addDays, dateKey, daysBetween, parseDate, prettyDate } from '../../shared/format'
import { decodeBrief } from '../courseEditor/brief'
import { useStudy } from '../../shared/StudyProvider'
import StudyDates from '../courseEditor/StudyDates'
import { Notice } from '../../shared/components/UI'
import { request } from '../../shared/request'
import type { SavedSchedule } from './ScheduleSuccessDialog'
import { getCourseWorkflow, lastScheduledDate, scheduleStrategies, studyDateKey, studyWeekdays } from './scheduleActions'
import type { Workflow } from './scheduleActions'
import './schedulePanel.css'

type Profile = NonNullable<StudyPlan['scheduling_profile']>

export default function SchedulePanel({ course, plan, courseSettings, inline = false, hideStudyDates = false, courseWorkflow, onSaved }: { course: CourseDetail; plan: StudyPlan; courseSettings?: { name: string; note: string; events: { title: string; date: string }[] }; inline?: boolean; hideStudyDates?: boolean; courseWorkflow?: Workflow | null; onSaved?: () => void }) {
  const { loadCourse, refreshCourses } = useStudy()
  const config = decodeBrief(course.student_brief)
  const initial = config.scheduling_profile ?? plan.scheduling_profile
  const [profile, setProfile] = useState<Profile>(() => ({
    start: initial?.start && initial.start >= dateKey() ? initial.start : config.startDate && config.startDate >= dateKey() ? config.startDate : dateKey(),
    end: initial?.end || config.deadline, daily_minutes: initial?.daily_minutes || 60,
    weekdays: initial?.weekdays || [0, 1, 2, 3, 4, 5, 6], off_dates: initial?.off_dates || [],
    priority_chapter_ids: initial?.priority_chapter_ids || [],
    strategy: initial?.strategy || 'auto', note: initial?.note || '',
  }))
  const [deadline, setDeadline] = useState(config.deadline || initial?.end || '')
  const [earlyDays, setEarlyDays] = useState(config.earlyDays || 0)
  const [dateToSkip, setDateToSkip] = useState('')
  const [localWorkflow, setWorkflow] = useState<Workflow | null>(null)
  const workflow = courseWorkflow === undefined ? localWorkflow : courseWorkflow
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<SavedSchedule['method']>(config.scheduling_mode ?? plan.schedule_mode ?? 'agent')

  useEffect(() => {
    if (courseWorkflow !== undefined) return
    let active = true
    void getCourseWorkflow(course.id).then((value) => {
      if (!active) return
      setWorkflow(value)
    }).catch((reason) => { if (active) setError(String(reason.message)) })
    return () => { active = false }
  }, [course.id, courseWorkflow, plan])

  const end = deadline && Number.isInteger(earlyDays) && earlyDays >= 0 ? addDays(deadline, -earlyDays) : ''
  const studyPeriod = profile.start && end
    ? `${prettyDate(profile.start, true)} – ${prettyDate(end, true)}`
    : ''
  const priorities = profile.priority_chapter_ids.filter(id => plan.chapters.some(chapter => chapter.id === id))
  const pendingTasks = plan.tasks.filter(task => task.status !== 'Completed')
  const lastStudyDates = pendingTasks.map(lastScheduledDate)
  const unscheduled = workflow?.unscheduled ?? lastStudyDates.filter(date => !date).length
  const overdue = workflow?.overdue ?? lastStudyDates.filter(date => date && date < studyDateKey()).length
  const canAddSkipDate = dateToSkip && !profile.off_dates.includes(dateToSkip)
  const offDates = canAddSkipDate ? [...profile.off_dates, dateToSkip].sort() : profile.off_dates
  const span = profile.start && end ? daysBetween(profile.start, end) : NaN
  const hasValidWindow = profile.start >= dateKey() && span >= 0 && span <= 365
  const studyDays = hasValidWindow
    ? Array.from({ length: span + 1 }, (_, offset) => addDays(profile.start, offset))
      .filter(day => profile.weekdays.includes((parseDate(day).getDay() + 6) % 7) && !offDates.includes(day)).length
    : null
  const budget = studyDays !== null && Number.isInteger(profile.daily_minutes) && profile.daily_minutes >= 1 && profile.daily_minutes <= 1440
    ? studyDays * profile.daily_minutes
    : null
  const estimate = workflow?.estimated_minutes
  const shortfall = budget !== null && estimate !== undefined ? Math.max(0, estimate - budget) : 0
  const allCompleted = plan.tasks.length > 0 && pendingTasks.length === 0
  const priorityChapters = priorities.flatMap(id => plan.chapters.filter(chapter => chapter.id === id))
  const otherChapters = plan.chapters.filter(chapter => !priorities.includes(chapter.id))
  const strategy = scheduleStrategies.find(item => item.value === profile.strategy) ?? scheduleStrategies[0]
  const strategyHelp = mode === 'baseline' && strategy.value === 'auto'
    ? 'Fixed rules use reading, practice, then review.'
    : strategy.help
  function addSkipDate() {
    if (!canAddSkipDate) return
    setProfile(current => ({ ...current, off_dates: [...current.off_dates, dateToSkip].sort() }))
    setDateToSkip('')
  }

  function movePriority(index: number, delta: number) {
    const next = [...priorities]
    const [chapterId] = next.splice(index, 1)
    next.splice(index + delta, 0, chapterId)
    setProfile(current => ({ ...current, priority_chapter_ids: next }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || (allCompleted && !courseSettings)) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      if (courseSettings && (!courseSettings.name.trim() || courseSettings.events.some(item => !item.title.trim() || !item.date))) throw new Error('Enter a course name and a title and full date for every event.')
      if (!profile.start || !end || end < profile.start) {
        throw new Error('Choose a study period that finishes on or after the start date.')
      }
      if (!hasValidWindow) throw new Error('Use a study period starting today or later and lasting at most 366 days.')
      if (!profile.weekdays.length) throw new Error('Choose at least one study day.')
      const schedule = {
        ...profile,
        end,
        off_dates: offDates,
        priority_chapter_ids: priorities,
      }
      await request(`/api/courses/${course.id}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: courseSettings?.name ?? course.name,
          note: courseSettings?.note ?? config.note,
          events: courseSettings?.events ?? config.events ?? [],
          startDate: profile.start,
          deadline,
          earlyDays,
          scheduling_profile: schedule,
          scheduling_mode: mode,
        }),
      })
      await Promise.allSettled([loadCourse(course.id), refreshCourses()])
      setProfile(schedule)
      setDateToSkip('')
      setMessage(allCompleted ? 'Settings saved. All learning tasks are complete.' : 'Study settings saved.')
      onSaved?.()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save study settings')
    } finally { setBusy(false) }
  }

  return (
    <section className={inline ? 'schedule-panel schedule-panel-inline' : 'panel schedule-panel'}>
      <header className="schedule-heading">
        <span className="schedule-heading-icon" aria-hidden="true"><CalendarDays size={21} /></span>
        <div>
          <h2>Daily learning schedule</h2>
          <p className="schedule-summary">
            <span>{plan.chapters.length} {plan.chapters.length === 1 ? 'chapter' : 'chapters'}</span>
            {unscheduled > 0 && <span>{unscheduled} {unscheduled === 1 ? 'task' : 'tasks'} to schedule</span>}
            {overdue > 0 && <span className="schedule-overdue">{overdue} overdue</span>}
          </p>
        </div>
      </header>

      {Boolean(workflow?.new_documents) && (
        <Notice>Some PDFs still need chapter analysis. This schedule uses the chapters already available.</Notice>
      )}

      <form className="schedule-form" onSubmit={event => void submit(event)}>
        <fieldset className="schedule-fields" disabled={busy} aria-label="Daily schedule settings">
          {hideStudyDates ? (
            <div className="schedule-window">
              <span>Study period</span>
              <strong>{studyPeriod || 'Set dates in Course settings'}</strong>
            </div>
          ) : (
            <StudyDates
              value={{ startDate: profile.start, deadline, earlyDays }}
              onChange={next => {
                setProfile(current => ({ ...current, start: next.startDate || '' }))
                setDeadline(next.deadline)
                setEarlyDays(next.earlyDays)
              }}
              disabled={busy}
            />
          )}

          <div className="schedule-input-grid">
            <label className="field">
              <span>Study time per day</span>
              <span className="schedule-unit-input">
                <input
                  type="number" required min={1} max={1440}
                  value={profile.daily_minutes}
                  onChange={event => setProfile({ ...profile, daily_minutes: Number(event.target.value) })}
                />
                <span aria-hidden="true">min</span>
              </span>
            </label>
            <label className="field">
              <span>Scheduling order</span>
              <select value={profile.strategy} onChange={event => setProfile({ ...profile, strategy: event.target.value })}>
                {scheduleStrategies.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <small className="muted">
                {strategy.value === 'weak_first' && priorities.length > 0
                  ? 'Your selected priority chapters come first, followed by weak chapters from the rest.'
                  : strategyHelp}
              </small>
            </label>
          </div>

          <fieldset className="schedule-weekdays">
            <legend>Study days</legend>
            <div className="schedule-day-options">
              {studyWeekdays.map((day, index) => (
                <label className="schedule-day" key={day}>
                  <input
                    type="checkbox"
                    checked={profile.weekdays.includes(index)}
                    onChange={event => {
                      const checked = event.target.checked
                      setProfile(current => ({
                        ...current,
                        weekdays: checked ? [...current.weekdays, index] : current.weekdays.filter(value => value !== index),
                      }))
                    }}
                  />
                  <span>{day}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="schedule-options">
            <details className="schedule-option">
              <summary>
                <CalendarX size={17} aria-hidden="true" />
                <span>Days off</span>
                {profile.off_dates.length > 0 && <small>{profile.off_dates.length} selected</small>}
                <ChevronDown className="schedule-chevron" size={16} aria-hidden="true" />
              </summary>
              <div className="schedule-option-body">
                <p className="muted small">Skip these dates even if they fall on a study day.</p>
                <div className="schedule-date-controls">
                  <label className="field">
                    <span className="sr-only">Date to skip</span>
                    <input
                      type="date" value={dateToSkip}
                      onChange={event => setDateToSkip(event.target.value)}
                      onKeyDown={event => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          addSkipDate()
                        }
                      }}
                    />
                  </label>
                  <button type="button" className="button secondary small" disabled={!canAddSkipDate} onClick={addSkipDate}>
                    <Plus size={15} aria-hidden="true" /> Add date
                  </button>
                </div>
                {profile.off_dates.length > 0 && (
                  <ul className="schedule-date-list">
                    {profile.off_dates.map(date => (
                      <li key={date}>
                        {prettyDate(date, true)}
                        <button
                          className="icon-button" type="button" aria-label={`Remove day off ${prettyDate(date, true)}`}
                          onClick={() => setProfile({ ...profile, off_dates: profile.off_dates.filter(item => item !== date) })}
                        >
                          <X size={14} aria-hidden="true" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </details>

            <details className="schedule-option">
              <summary>
                <ListOrdered size={17} aria-hidden="true" />
                <span>Priority chapters</span>
                {priorities.length > 0 && <small>{priorities.length} selected</small>}
                <ChevronDown className="schedule-chevron" size={16} aria-hidden="true" />
              </summary>
              <div className="schedule-option-body">
                <p className="muted small">Set the order of the chapters you want to study first.</p>
                <div className="schedule-chapter-list">
                  {priorityChapters.map((chapter, index) => (
                    <div key={chapter.id} className="schedule-priority-row">
                      <label className="schedule-chapter">
                        <input type="checkbox" checked onChange={() => setProfile({
                          ...profile, priority_chapter_ids: priorities.filter(id => id !== chapter.id),
                        })} />
                        <span className="schedule-priority-number" aria-label={`Priority ${index + 1}`}>{index + 1}</span>
                        <span>{chapter.title}</span>
                      </label>
                      <div className="schedule-priority-controls">
                        <button type="button" className="icon-button" disabled={index === 0}
                          aria-label={`Move ${chapter.title} up`} onClick={() => movePriority(index, -1)}>
                          <ArrowUp size={15} aria-hidden="true" />
                        </button>
                        <button type="button" className="icon-button" disabled={index === priorityChapters.length - 1}
                          aria-label={`Move ${chapter.title} down`} onClick={() => movePriority(index, 1)}>
                          <ArrowDown size={15} aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {otherChapters.map(chapter => (
                    <label key={chapter.id} className="schedule-chapter">
                      <input
                        type="checkbox"
                        checked={false}
                        onChange={() => setProfile({ ...profile, priority_chapter_ids: [...priorities, chapter.id] })}
                      />
                      <span>{chapter.title}</span>
                    </label>
                  ))}
                </div>
              </div>
            </details>
          </div>

          <details className="schedule-method">
            <summary>Planning method</summary>
            <label className="field">
              <span className="sr-only">Planning method</span>
              <select value={mode} onChange={event => setMode(event.target.value === 'baseline' ? 'baseline' : 'agent')}>
                <option value="agent">AI planner</option>
                <option value="baseline">Fixed rules</option>
              </select>
            </label>
            <p className="muted small">
              {mode === 'agent'
                ? 'With Automatic order, AI can choose a strategy based on your progress. Every plan is checked before it is saved.'
                : 'Follows your chosen order and checks the schedule. With Automatic order, it starts with reading.'}
            </p>
          </details>

          <div className="schedule-budget" aria-live="polite">
            <strong>Study time budget</strong>
            {allCompleted ? <span>All tasks completed.</span> : <>
              {budget !== null && <span>{budget} min available</span>}
              {estimate !== undefined && estimate > 0 && <span>{estimate} min estimated for remaining tasks</span>}
              {shortfall > 0 && <span className="schedule-overdue">Short by {shortfall} min. Add study days or increase daily study time.</span>}
            </>}
          </div>
          <div className="schedule-footer">
            <p className="muted small">Longer tasks can span several days.</p>
            <button className="button" type="submit" disabled={busy || !plan.chapters.length || (allCompleted && !courseSettings)}>
              {busy ? 'Saving…' : 'Save settings'}
            </button>
          </div>
        </fieldset>
      </form>
      {message && (
        <Notice tone="success">
          {message}
          {!allCompleted && ' Use Replan remaining tasks below to preview the schedule.'}
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
    </section>
  )
}
