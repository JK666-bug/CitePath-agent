import { request } from '../../shared/request'
import type {
  CourseDetail,
  QAResponse,
  StudyPlan,
} from './types'

export function deleteCourse(id: number) {
  return request<{ ok: boolean }>(
    `/api/courses/${id}`,
    { method: 'DELETE' },
  )
}

export function getCourse(id: number) {
  return request<CourseDetail>(
    `/api/courses/${id}`,
  )
}

export function uploadMaterial(
  id: number,
  file: File,
) {
  const body = new FormData()
  body.append('file', file)

  return request<{
    document_id: number
    filename: string
    page_count: number
    usable_page_count: number
    milvus_segments: number
    duplicate: boolean
  }>(
    `/api/courses/${id}/documents`,
    {
      method: 'POST',
      body,
    },
  )
}

export function duplicateMessage(
  selected: string,
  stored: string,
) {
  if (selected === stored) {
    return (
      `${selected} is already in this course` +
      ' and was not uploaded again.'
    )
  }

  return (
    `${selected} matches ${stored}, which is already` +
    ' in this course, and was not uploaded again.'
  )
}

export function deleteMaterial(
  courseId: number,
  documentId: number,
) {
  return request<{ ok: boolean }>(
    `/api/courses/${courseId}/documents/${documentId}`,
    {
      method: 'DELETE',
    },
  )
}

export type PlanResponse = {
  status: string
  plan: StudyPlan | null
}

export function getPlan(id: number) {
  return request<PlanResponse>(
    `/api/courses/${id}/plan`,
  )
}

export function createPlan(
  id: number,
  start: string,
  end: string,
  note: string,
) {
  return request<PlanResponse>(
    `/api/courses/${id}/plan`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ start, end, note }),
    },
  )
}

export function completePlanTask(
  courseId: number,
  taskId: string,
) {
  return request<PlanResponse>(
    `/api/courses/${courseId}/plan/tasks/${encodeURIComponent(taskId)}/complete`,
    { method: 'POST' },
  )
}

export function listQuestions(courseId: number) {
  return request<QAResponse[]>(
    `/api/courses/${courseId}/questions`,
  )
}

export function askCourse(
  courseId: number,
  question: string,
) {
  return request<QAResponse>(
    `/api/courses/${courseId}/questions`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question }),
    },
  )
}