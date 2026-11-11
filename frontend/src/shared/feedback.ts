import type { Source } from '../pages/course/types'

export type ExplanationFields = {
  explanation_status?: 'not_required' | 'pending' | 'failed' | 'ready'
  explanation_error?: string | null
  explanation_attempts?: number
}

export type ReportNarrative = {
  summary?: string
  round_summaries?: string[]
  review_guidance?: { concept: string; text: string; sources: Source[] }[]
  feedback_pending_count?: number
}

export type MarkingFields = {
  rubric?: string[]
  rubric_hits?: number[] | null
  points_hit?: number
  points_total?: number
}
