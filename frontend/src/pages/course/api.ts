import { ApiError, request } from '../../shared/request'
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

export function documentFileUrl(
  courseId: number,
  documentId: number,
) {
  return `/api/courses/${courseId}/documents/${documentId}/file`
}

export async function downloadNotes(
  courseId: number,
  brief: string,
  documentIds: number[],
  mode: 'notes' | 'cheatsheet' = 'notes',
  paperSize: 'a4' | 'a5' | 'letter' = 'a4',
  sides: 'single' | 'double' = 'single',
  typeSize: 'large' | 'medium' | 'small' | 'tiny' = 'medium',
) {
  const response = await fetch(`/api/courses/${courseId}/notes`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      brief,
      document_ids: documentIds,
      mode,
      paper_size: paperSize,
      sides: mode === 'cheatsheet' ? sides : 'single',
      type_size: mode === 'cheatsheet' ? typeSize : 'medium',
    }),
  })
  if (!response.ok) {
    let detail = 'Could not generate notes'
    try {
      const payload = await response.json()
      if (payload && typeof payload.detail === 'string') {
        detail = payload.detail
      }
    } catch {
      // keep default
    }
    throw new ApiError(response.status, detail)
  }
  const blob = await response.blob()
  const header = response.headers.get('Content-Disposition') || ''
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(
    header,
  )
  const filename = decodeURIComponent(
    match?.[1] || match?.[2] || 'course-notes.pdf',
  )
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export type VectorSegment = {
  document_id: number
  page_number: number
  chunk_index: number
  chapter: string
  text: string
}

export function getDocumentSegments(
  courseId: number,
  documentId: number,
) {
  return request<{
    collection: string
    document_id: number
    filename: string
    count: number
    segments: VectorSegment[]
  }>(
    `/api/courses/${courseId}/documents/${documentId}/segments`,
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

export type ExamCaseAnswerMode = 'none' | 'in_case' | 'file'

export type ExamCase = {
  id: number
  position: number
  filename: string
  ingest_status: string
  answer_mode: ExamCaseAnswerMode
  page_count: number
  usable_page_count: number
  answer_file: {
    id: number
    filename: string
    ingest_status: string
    page_count: number
    usable_page_count: number
  } | null
}

export function listExamCases(courseId: number) {
  return request<{ cases: ExamCase[] }>(
    `/api/courses/${courseId}/exam-cases`,
  )
}

export function uploadExamCase(
  courseId: number,
  file: File,
  answerMode: ExamCaseAnswerMode,
  answerFile?: File | null,
) {
  const body = new FormData()
  body.append('file', file)
  body.append('answer_mode', answerMode)
  if (answerMode === 'file' && answerFile) {
    body.append('answer_file', answerFile)
  }
  return request<{
    document_id: number
    filename: string
    page_count: number
    usable_page_count: number
    milvus_segments: number
    duplicate: boolean
    answer_mode: ExamCaseAnswerMode
    answer_file: ExamCase['answer_file']
  }>(`/api/courses/${courseId}/exam-cases`, {
    method: 'POST',
    body,
  })
}

export function deleteExamCase(
  courseId: number,
  documentId: number,
) {
  return request<{ ok: boolean }>(
    `/api/courses/${courseId}/exam-cases/${documentId}`,
    { method: 'DELETE' },
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
  documentIds: number[],
) {
  return request<PlanResponse>(
    `/api/courses/${id}/plan`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        start,
        end,
        note,
        document_ids: documentIds,
      }),
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
  documentIds: number[],
  tabId?: string | null,
  includeWeb = false,
  chat = false,
) {
  return request<QAResponse>(
    `/api/courses/${courseId}/questions`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
        document_ids: documentIds,
        tab_id: tabId || undefined,
        include_web: includeWeb,
        chat,
      }),
    },
  )
}

export function deleteQuestionTab(courseId: number, tabId: string) {
  return request<{ ok: boolean }>(
    `/api/courses/${courseId}/questions/tabs/${encodeURIComponent(tabId)}`,
    { method: 'DELETE' },
  )
}