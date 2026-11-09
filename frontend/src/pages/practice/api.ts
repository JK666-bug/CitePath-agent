import { request } from '../../shared/request'
import type { Source } from '../course/types'

export type PracticeQuestion = {
  id: number
  concept_name: string
  kind: 'mcq' | 'short'
  prompt: string
  options: string[]
  sources: Source[]
}

export type PracticeFeedback = {
  concept_name: string
  correct: boolean
  explanation: string
  answer: string
}

export type PracticeConcept = {
  id: number
  name: string
  level: number
  streak: number
}

export type PracticeReport = {
  started_at: string
  finished_at: string
  question_count: number
  correct_count: number
  wrong_count: number
  session_count?: number
  concepts: {
    name: string
    attempts: number
    correct: number
    level: number
  }[]
  wrong: {
    question_id: number
    concept_name: string
    kind: string
    phase: string
    prompt: string
    response: string
    options?: string[]
    answer: string
    explanation: string
    sources: Source[]
    correct?: boolean
  }[]
  questions?: {
    question_id: number
    concept_name: string
    kind: string
    phase: string
    prompt: string
    response: string
    options?: string[]
    answer: string
    explanation: string
    sources: Source[]
    correct: boolean
  }[]
}

export type PracticeSession = {
  id: number
  course_id: number
  chapter_id: number
  chapter_title: string
  status: 'open' | 'finished'
  phase: 'learn' | 'review'
  question: PracticeQuestion | null
  feedback: PracticeFeedback | null
  report: PracticeReport | null
  concepts: PracticeConcept[]
}

export function createPractice(
  courseId: number,
  chapterId: number,
) {
  return request<PracticeSession>(
    `/api/courses/${courseId}/chapters/${chapterId}/practice`,
    { method: 'POST' },
  )
}

export function getPractice(
  courseId: number,
  sessionId: number,
) {
  return request<PracticeSession>(
    `/api/courses/${courseId}/practice/${sessionId}`,
  )
}

export function answerPractice(
  courseId: number,
  sessionId: number,
  questionId: number,
  response: string,
) {
  return request<PracticeSession>(
    `/api/courses/${courseId}/practice/${sessionId}/answer`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question_id: questionId,
        response,
      }),
    },
  )
}

export type ChapterReports = {
  chapter_id: number
  chapter_title: string
  practice: {
    id: number
    started_at: string
    finished_at: string
    question_count: number
    correct_count: number
    wrong_count: number
  }[]
  exams: {
    id: number
    started_at: string
    finished_at: string
    score: number | null
    passed: boolean
    correct_count: number
    total: number
    wrong_count: number
  }[]
}

export function listReports(
  courseId: number,
  chapterId: number,
) {
  return request<ChapterReports>(
    `/api/courses/${courseId}/chapters/${chapterId}/reports`,
  )
}
