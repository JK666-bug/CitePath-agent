//集中定义课程、任务和练习的数据格式。
export type CourseConfig = {
  deadline: string
  earlyDays: number
  note: string
}

export type Material = {
  id: number
  position: number
  filename: string
  ingest_status: string
  ingest_error?: string | null
  page_count: number
  usable_page_count: number
}

export type MaterialInventory = Omit<Material, 'position'> & {
  position: number | null
  active: boolean
  removed_at: string
  sha256: string | null
  original_pdf_available: boolean
  page_numbers: number[]
}

export type CourseDetail = {
  id: number
  name: string
  student_brief: string
  created_at: string
  documents: Material[]
}

export type Source = {
  document_id: number
  position?: number | null
  filename: string
  page_number: number
}

export type Task = {
  id: string
  chapterId: string
  title: string
  kind: 'Reading' | 'Practice' | 'Review'
  date: string
  status:
    | 'Not started'
    | 'In progress'
    | 'Completed'
  sources: Source[]
  concepts: string[]
  estimated_minutes?: number
}

export type Chapter = {
  id: string
  title: string
  concepts: string[]
  sources: Source[]
  estimated_minutes?: number
  estimate_basis?: string
}

export type PlanningProfile = {
  goal: string
  prior_knowledge: string
  daily_minutes: number
  reading_words_per_minute?: number
  assumptions?: string[]
}

export type PlanQuestion = {
  id: 'goal' | 'prior_knowledge' | 'daily_minutes'
  prompt: string
  required: boolean
}

export type MaterialUpdate = {
  new_page_count: number
  new_document_ids: number[]
  missing_document_ids: number[]
  can_update: boolean
}

export type StudyPlan = {
  version: number
  start: string
  end?: string
  tasks: Task[]
  chapters: Chapter[]
  reason: string
  planning_profile?: PlanningProfile
  estimated_total_minutes?: number
  estimated_remaining_minutes?: number
  estimate_basis?: string
  capacity?: { available_minutes: number; remaining_estimated_minutes: number; over_capacity: boolean }
}

export type CalendarTask = Task & {
  courseId: string
  courseName: string
}

export type Question = {
  id: string
  kind: 'mcq' | 'short'
  prompt: string
  options: string[]
  correct: string
  rubric: string[]
  explanation: string
  sources: Source[]
}

export type QuestionResult = {
  questionId: string
  correct: boolean
  hits: string[]
  explanation: string
}

export type RoundResult = {
  round: 1 | 2
  score: number
  passed: boolean
  answers: Record<string, string>
  questions: QuestionResult[]
}

export type PracticeSession = {
  chapterId: string
  round: 1 | 2
  status:
    | 'Answering'
    | 'Review required'
    | 'Ended'
  answers: Record<string, string>
  history: RoundResult[]
}

export type DemoState = {
  schema: 1
  course: CourseDetail
  plan: StudyPlan
  sessions: Record<string, PracticeSession>
}

export type QAResponse = {
  qa_id: number
  course_name: string
  question?: string
  answer: string
  cited_pages: Source[]
  web_sources?: { title: string; url: string }[]
  refused: boolean
  origin?: string
}
