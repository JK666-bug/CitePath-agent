import { request } from '../../shared/request'
import type { SavedSchedule, ScheduleStep, ScheduleSummary } from './ScheduleSuccessDialog'
import type { CourseConfig, StudyPlan, Task } from './types'

export type Workflow = {
  documents: { id: number; state: 'unplanned' | 'planned' | 'locked' }[]
  unscheduled: number
  overdue: number
  new_documents: number
  estimated_minutes: number
  study_time_samples?: Partial<Record<'Reading' | 'Practice', number>>
}

export function getCourseWorkflow(courseId: number) {
  return request<Workflow>(`/api/courses/${courseId}/workflow`)
}

type ScheduleResult = {
  status: string
  run_id: string
  message: string
  trace?: ScheduleStep[]
  summary?: ScheduleSummary
  mode?: SavedSchedule['method']
  start?: string
  unchanged?: boolean
}

export function lastScheduledDate(task: Task) {
  return task.schedule?.reduce((latest, slot) => slot.date > latest ? slot.date : latest, '') || task.date || ''
}

export function hasUnappliedSettings(config: CourseConfig, plan: StudyPlan | null | undefined) {
  const published = plan?.schedule_preferences ?? plan?.scheduling_profile
  const saved = config.scheduling_profile
  if (!plan?.schedule_run_id || !published || !saved) return false
  return (config.scheduling_mode != null && config.scheduling_mode !== plan.schedule_mode) ||
    (Object.keys(published) as (keyof typeof published)[]).some(
      key => JSON.stringify(published[key]) !== JSON.stringify(saved[key]),
    )
}

export function studyDateKey() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Hong_Kong', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts()
  const date = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${date.year}-${date.month}-${date.day}`
}

export function scheduleForDialog(
  result: ScheduleResult,
  method: SavedSchedule['method'],
  start = studyDateKey(),
): SavedSchedule {
  return {
    method: result.mode ?? method,
    start: result.start ?? start,
    steps: result.trace ?? [],
    summary: result.summary,
    unchanged: result.unchanged,
  }
}

export function scheduleReviewHref(courseId: number | string) {
  return `/courses/${courseId}/plan?review=schedule`
}

export function previewSchedule(courseId: number, requestId: string) {
  return request<ScheduleResult>(`/api/courses/${courseId}/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, preview: true }),
  })
}

export function applySchedule(courseId: number, runId: string) {
  return request<ScheduleResult>(`/api/courses/${courseId}/schedule/${encodeURIComponent(runId)}/apply`, { method: 'POST' })
}

export function logStudyTime(courseId: number, taskId: string, minutes: number) {
  return request<{ minutes: number }>(`/api/courses/${courseId}/tasks/${encodeURIComponent(taskId)}/study-time`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ minutes }),
  })
}
export const studyWeekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const scheduleStrategies = [
  { value: 'auto', label: 'Automatic', help: 'Uses your learning progress to choose an order.' },
  { value: 'new_first', label: 'Reading first', help: 'Prioritizes reading, then practice and review.' },
  { value: 'weak_first', label: 'Weak chapters first', help: 'Prioritizes chapters with an exam still to pass or concepts still to master.' },
  { value: 'chapter_order', label: 'Chapter order', help: 'Follows the order in your chapter list.' },
]
