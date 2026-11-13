import { request } from '../../shared/request'
import type { Source } from '../course/types'
import type { ExplanationFields, MarkingFields, ReportNarrative } from '../../shared/feedback'

export type PracticeQuestion = {
  id: number
  concept_name: string
  kind: 'mcq' | 'short'
  prompt: string
  options: string[]
  sources: Source[]
  response?: string
}

export type PracticeFeedback = ExplanationFields & MarkingFields & {
  question_id?: number
  concept_name: string
  correct: boolean
  explanation: string
  answer: string
  sources?: Source[]
}

export type PracticeRoundResult = {
  round_number: 1 | 2
  correct_count: number
  total: number
  accuracy: number
  score: number
  passed: boolean
  weak_concepts: string[]
}

export function practiceOutcome(outcome?: string): string {
  if (outcome === 'passed_round_1') return 'Passed in round 1'
  if (outcome === 'passed_round_2') return 'Passed in round 2'
  if (outcome === 'failed_after_2') return 'Ended after round 2 · Not passed'
  return 'Previous practice record'
}

export type PracticeConcept = {
  id: number
  name: string
  level: number
  streak: number
}

export type PracticeReport = ReportNarrative & {
  started_at: string
  finished_at: string
  question_count: number
  correct_count: number
  wrong_count: number
  session_count?: number
  rounds?: PracticeRoundResult[]
  passing_threshold?: number
  passed?: boolean
  outcome?: 'passed_round_1' | 'passed_round_2' | 'failed_after_2' | 'legacy'
  remaining_weak_concepts?: string[]
  remaining_sources?: Source[]
  concepts: {
    name: string
    attempts: number
    correct: number
    level: number
  }[]
  wrong: (ExplanationFields & MarkingFields & {
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
  })[]
  questions?: (ExplanationFields & MarkingFields & {
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
  })[]
}

export type PracticeSession = {
  id: number
  course_id: number
  chapter_id: number
  chapter_title: string
  status: 'open' | 'finished'
  phase: 'learn' | 'review'
  round_number?: 1 | 2
  passing_threshold?: number
  answered_count?: number
  round_question_count?: number
  round_results?: PracticeRoundResult[]
  migration_notice?: string
  question: PracticeQuestion | null
  feedback: PracticeFeedback | null
  report: PracticeReport | null
  concepts: PracticeConcept[]
}

export function createPractice(
  courseId: number,
  chapterId: number,
  passingThreshold = 0.8,
) {
  return request<PracticeSession>(
    `/api/courses/${courseId}/chapters/${chapterId}/practice`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passing_threshold: passingThreshold }),
    },
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

export function savePracticeDraft(
  courseId: number,
  sessionId: number,
  questionId: number,
  response: string,
) {
  return request<{ saved: boolean; question_id: number }>(
    `/api/courses/${courseId}/practice/${sessionId}/draft`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_id: questionId, response }),
    },
  )
}

export function retryPracticeExplanation(courseId: number, sessionId: number, questionId: number) {
  return request<PracticeSession>(
    `/api/courses/${courseId}/practice/${sessionId}/questions/${questionId}/explanation/retry`,
    { method: 'POST' },
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
