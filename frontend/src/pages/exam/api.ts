import { request } from '../../shared/request'
import type { Source } from '../course/types'
import type { ExplanationFields, MarkingFields, ReportNarrative } from '../../shared/feedback'

export type ExamQuestion = ExplanationFields & MarkingFields & {
  id: number
  position: number
  concept_name: string
  kind: 'mcq' | 'short'
  prompt: string
  options: string[]
  sources: Source[]
  response?: string
  correct?: boolean
  answer?: string
  rubric?: string[]
  explanation?: string
  points_hit?: number
  points_total?: number
}

export type ExamWrong = ExplanationFields & MarkingFields & {
  question_id: number
  concept_name: string
  kind: string
  prompt: string
  response: string
  answer: string
  explanation: string
  sources: Source[]
}

export type ExamRecord = {
  id: number
  course_id: number
  chapter_id: number
  chapter_title: string
  status: 'open' | 'finished'
  score: number | null
  passed: boolean | null
  report: ReportNarrative & {
    score: number
    passed: boolean
    correct_count: number
    total: number
    wrong_count: number
    wrong: ExamWrong[]
  } | null
  questions: ExamQuestion[]
}

export function createExam(
  courseId: number,
  chapterId: number,
) {
  return request<ExamRecord>(
    `/api/courses/${courseId}/chapters/${chapterId}/exams`,
    { method: 'POST' },
  )
}

export function getExam(
  courseId: number,
  examId: number,
) {
  return request<ExamRecord>(
    `/api/courses/${courseId}/exams/${examId}`,
  )
}

export function saveExamDraft(
  courseId: number,
  examId: number,
  answers: { question_id: number; response: string }[],
) {
  return request<ExamRecord>(
    `/api/courses/${courseId}/exams/${examId}/drafts`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ answers }),
    },
  )
}

export function submitExam(
  courseId: number,
  examId: number,
  answers: { question_id: number; response: string }[],
) {
  return request<ExamRecord>(
    `/api/courses/${courseId}/exams/${examId}/submit`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ answers }),
    },
  )
}

export function retryExamExplanation(courseId: number, examId: number, questionId: number) {
  return request<ExamRecord>(
    `/api/courses/${courseId}/exams/${examId}/questions/${questionId}/explanation/retry`,
    { method: 'POST' },
  )
}
