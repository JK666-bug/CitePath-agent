import { request } from '../../shared/request'
import type { SavedSchedule, ScheduleStep, ScheduleSummary } from './ScheduleSuccessDialog'

export type Workflow = {
  documents: { id: number; state: 'unplanned' | 'planned' | 'locked' }[]
  unscheduled: number
  overdue: number
  new_documents: number
  estimated_minutes: number
}

export function getCourseWorkflow(courseId: number) {
  return request<Workflow>(`/api/courses/${courseId}/workflow`)
}

type ScheduleResult = {
  status: string
  message: string
  trace?: ScheduleStep[]
  summary?: ScheduleSummary
  mode?: SavedSchedule['method']
  start?: string
}

export function requestSchedule(
  courseId: number,
  settings?: { profile: Record<string, unknown>; mode: SavedSchedule['method'] },
) {
  return request<ScheduleResult>(`/api/courses/${courseId}/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: crypto.randomUUID(), ...settings }),
  })
}

export const studyWeekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const scheduleStrategies = [
  { value: 'auto', label: 'Automatic', help: 'Uses your learning progress to choose an order.' },
  { value: 'new_first', label: 'Reading first', help: 'Prioritizes reading, then practice and review.' },
  { value: 'weak_first', label: 'Weak chapters first', help: 'Prioritizes chapters with an exam still to pass or concepts still to master.' },
  { value: 'chapter_order', label: 'Chapter order', help: 'Follows the order in your chapter list.' },
]
