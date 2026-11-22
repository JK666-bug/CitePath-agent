//集中定义课程、任务和练习的数据格式。
export type CourseConfig = {
  startDate?: string
  deadline: string
  earlyDays: number
  note: string
  events?: { title: string; date: string }[]
  scheduling_profile?: Partial<NonNullable<StudyPlan['scheduling_profile']>>
  scheduling_mode?: StudyPlan['schedule_mode']
}

export type Material = {
  id: number
  position: number
  filename: string
  ingest_status: string
  page_count: number
  usable_page_count: number
  has_file?: boolean
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
  position?: number
  filename: string
  page_number: number
}

export type Task = {
  id: string
  chapterId: string
  title: string
  kind: 'Reading' | 'Practice' | 'Review'
  date: string
  schedule?: { date: string; minutes: number }[]
  estimated_minutes?: number
  estimate_basis?: string
  study_time?: { minutes: number }
  status:
    | 'Not started'
    | 'In progress'
    | 'Completed'
  completion_source?:
    | 'student'
    | 'practice_submit'
    | 'exam_pass'
    | ''
  sources: Source[]
  concepts: string[]
}

export type ChapterPracticeProgress = {
  open_session_id: number | null
  has_finished: boolean
  mastered: number
  total: number
}

export type Chapter = {
  id: string
  title: string
  concepts: string[]
  sources: Source[]
  practice_progress?: ChapterPracticeProgress
  chapter_status?:
    | 'planned'
    | 'learning'
    | 'learned'
    | 'practice_in_progress'
    | 'exam_pending'
    | 'completed'
  review_status?:
    | 'not_assessed'
    | 'required'
    | 'passed'
}

export type StudyPlan = {
  version: number
  start: string
  end?: string
  tasks: Task[]
  chapters: Chapter[]
  reason: string
  schedule_run_id?: string
  schedule_mode?: 'agent' | 'baseline'
  schedule_preferences?: StudyPlan['scheduling_profile']
  scheduling_profile?: {
    start: string; end: string; daily_minutes: number; weekdays: number[]
    off_dates: string[]; priority_chapter_ids: string[]; strategy: string; note: string
  }
}

export type CalendarTask = Task & {
  courseId: string
  courseName: string
  minutes?: number
  practice_progress?: ChapterPracticeProgress
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
  tab_id?: string
  tab_title?: string
  created_at?: string
}
