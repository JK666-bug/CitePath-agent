import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'

import type { ReactNode } from 'react'

import { deleteCourse } from '../pages/course/api'
import {
  decodeBrief,
  encodeBrief,
} from '../pages/courseEditor/brief'
import { getCourses } from '../pages/courses/api'
import type { CourseSummary } from '../pages/courses/api'

import {
  completePlanTask,
  createPlan,
  getCourse,
  getPlan,
} from '../pages/course/api'

import {
  createDemo,
  nextDemoRound,
  scheduleDemo,
  startDemoSession,
  submitDemo,
} from '../pages/course/demo'

import type {
  CourseConfig,
  CourseDetail,
  DemoState,
  StudyPlan,
} from '../pages/course/types'

import { messageOf } from './request'

type PlanEntry = {
  plan: StudyPlan | null
  loaded: boolean
  loading: boolean
  error: string
  generating: boolean
}

function loadDemo(key: string): DemoState {
  try {
    const raw = localStorage.getItem(key)

    if (raw) {
      const value = JSON.parse(raw) as DemoState

      if (
        value.schema === 1 &&
        value.course?.id === -1 &&
        Array.isArray(value.course.documents) &&
        Array.isArray(value.plan?.tasks) &&
        Array.isArray(value.plan.chapters) &&
        value.sessions &&
        typeof value.sessions === 'object'
      ) {
        return value
      }
    }
  } catch {
    // Start a fresh demo if storage is unavailable.
  }

  return createDemo()
}

function useStudyValue(userId: number) {
  const key =
    `citepath-interface-demo-v1-${userId}`

  const [courses, setCourses] =
    useState<CourseSummary[]>([])

  const [coursesLoading, setCoursesLoading] =
    useState(true)

  const [coursesError, setCoursesError] =
    useState('')

  const [details, setDetails] = useState<
    Record<number, CourseDetail>
  >({})

  const [demo, setDemo] = useState<DemoState>(
    () => loadDemo(key),
  )

  const [storageError, setStorageError] =
    useState('')

  const [plans, setPlans] = useState<
    Record<number, PlanEntry>
  >({})

  const generatingIds = useRef(
    new Set<number>(),
  )

  const refreshCourses = useCallback(async () => {
    setCoursesLoading(true)
    setCoursesError('')

    try {
      setCourses(await getCourses())
    } catch (error) {
      setCoursesError(messageOf(error))
    } finally {
      setCoursesLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshCourses()
  }, [refreshCourses])

  useEffect(() => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify(demo),
      )

      setStorageError('')
    } catch {
      setStorageError(
        'Demo changes cannot be saved in this browser. Keep this tab open to retain your current session.',
      )
    }
  }, [demo, key])

  const removeCourse = useCallback(
    async (id: number) => {
      await deleteCourse(id)

      setCourses((current) =>
        current.filter(
          (course) => course.id !== id,
        ),
      )

      setDetails((current) => {
        const next = { ...current }
        delete next[id]
        return next
      })

      setPlans((current) => {
        const next = { ...current }
        delete next[id]
        return next
      })
    },
    [],
  )

  const loadCourse = useCallback(
    async (id: number) => {
      const result = await getCourse(id)

      setDetails((current) => ({
        ...current,
        [id]: result,
      }))

      return result
    },
    [],
  )

  const loadPlan = useCallback(async (id: number) => {
    if (generatingIds.current.has(id)) {
      return
    }

    setPlans((current) => ({
      ...current,
      [id]: {
        plan: current[id]?.plan ?? null,
        loaded: current[id]?.loaded ?? false,
        loading: true,
        error: '',
        generating: false,
      },
    }))

    try {
      const result = await getPlan(id)

      if (generatingIds.current.has(id)) {
        return
      }

      setPlans((current) => ({
        ...current,
        [id]: {
          plan: result.plan,
          loaded: true,
          loading: false,
          error: '',
          generating: false,
        },
      }))
    } catch (error) {
      if (generatingIds.current.has(id)) {
        return
      }

      setPlans((current) => ({
        ...current,
        [id]: {
          plan: current[id]?.plan ?? null,
          loaded: true,
          loading: false,
          error: messageOf(error),
          generating: false,
        },
      }))
    }
  }, [])

  const generateCoursePlan = useCallback(
    async (id: number, start: string, end: string, note: string) => {
      generatingIds.current.add(id)

      setPlans((current) => ({
        ...current,
        [id]: {
          plan: current[id]?.plan ?? null,
          loaded: true,
          loading: false,
          error: '',
          generating: true,
        },
      }))

      try {
        const result = await createPlan(id, start, end, note)
        const savedNote = note.trim()

        setDetails((current) => {
          const course = current[id]
          if (!course) return current
          const config = decodeBrief(course.student_brief)
          return {
            ...current,
            [id]: {
              ...course,
              student_brief: encodeBrief({
                ...config,
                note: savedNote,
              }),
            },
          }
        })

        setCourses((current) =>
          current.map((course) => {
            if (course.id !== id) return course
            const config = decodeBrief(course.student_brief)
            return {
              ...course,
              student_brief: encodeBrief({
                ...config,
                note: savedNote,
              }),
            }
          }),
        )

        setPlans((current) => ({
          ...current,
          [id]: {
            plan: result.plan,
            loaded: true,
            loading: false,
            error: '',
            generating: false,
          },
        }))
      } catch (error) {
        setPlans((current) => ({
          ...current,
          [id]: {
            plan: current[id]?.plan ?? null,
            loaded: true,
            loading: false,
            error: messageOf(error),
            generating: false,
          },
        }))
      } finally {
        generatingIds.current.delete(id)
      }
    },
    [],
  )

  const finishPlanTask = useCallback(
    async (id: number, taskId: string) => {
      try {
        const result = await completePlanTask(
          id,
          taskId,
        )

        setPlans((current) => ({
          ...current,
          [id]: {
            plan: result.plan,
            loaded: true,
            loading: false,
            error: '',
            generating:
              current[id]?.generating ?? false,
          },
        }))
      } catch (error) {
        setPlans((current) => ({
          ...current,
          [id]: {
            plan: current[id]?.plan ?? null,
            loaded: true,
            loading: false,
            error: messageOf(error),
            generating:
              current[id]?.generating ?? false,
          },
        }))
      }
    },
    [],
  )

  useEffect(() => {
    for (const course of courses) {
      void loadPlan(course.id)
    }
  }, [courses, loadPlan])

  function editDemo(
    name: string,
    config: CourseConfig,
  ) {
    setDemo((current) => ({
      ...current,
      course: {
        ...current.course,
        name,
        student_brief: encodeBrief(config),
      },
      plan: scheduleDemo(
        current.plan,
        config,
        'Sample course settings changed; completed tasks were preserved.',
      ),
    }))
  }

  function completeTask(id: string) {
    setDemo((current) => ({
      ...current,
      plan: {
        ...current.plan,
        tasks: current.plan.tasks.map((task) =>
          task.id === id &&
          task.kind !== 'Practice'
            ? { ...task, status: 'Completed' }
            : task,
        ),
      },
    }))
  }

  function setAnswer(
    chapterId: string,
    questionId: string,
    answer: string,
  ) {
    setDemo((current) => {
      const session =
        current.sessions[chapterId]

      if (
        !session ||
        session.status !== 'Answering'
      ) {
        return current
      }

      return {
        ...current,
        sessions: {
          ...current.sessions,
          [chapterId]: {
            ...session,
            answers: {
              ...session.answers,
              [questionId]: answer,
            },
          },
        },
      }
    })
  }

  return {
    courses,
    coursesLoading,
    coursesError,
    refreshCourses,
    removeCourse,
    details,
    loadCourse,
    plans,
    loadPlan,
    generateCoursePlan,
    finishPlanTask,
    demo,
    storageError,
    editDemo,
    completeTask,
    setAnswer,

    startPractice: (id: string) =>
      setDemo((current) =>
        startDemoSession(current, id),
      ),

    submitPractice: (id: string) =>
      setDemo((current) =>
        submitDemo(current, id),
      ),

    nextRound: (id: string) =>
      setDemo((current) =>
        nextDemoRound(current, id),
      ),

    resetDemo: () => setDemo(createDemo()),
  }
}

const StudyContext = createContext<
  ReturnType<typeof useStudyValue> | null
>(null)

export function StudyProvider({
  userId,
  children,
}: {
  userId: number
  children: ReactNode
}) {
  const value = useStudyValue(userId)

  return (
    <StudyContext.Provider value={value}>
      {children}
    </StudyContext.Provider>
  )
}

export function useStudy() {
  const value = useContext(StudyContext)

  if (!value) {
    throw new Error(
      'StudyProvider is required.',
    )
  }

  return value
}

export function useCourse(id: string) {
  const {
    demo,
    details,
    loadCourse,
  } = useStudy()

  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  const valid =
    id === 'demo' ||
    /^[1-9]\d*$/.test(id)

  useEffect(() => {
    if (id === 'demo' || !valid) {
      return
    }

    let active = true
    setError('')

    loadCourse(Number(id)).catch((reason) => {
      if (active) {
        setError(messageOf(reason))
      }
    })

    return () => {
      active = false
    }
  }, [id, valid, loadCourse, attempt])

  return {
    course:
      id === 'demo'
        ? demo.course
        : details[Number(id)],

    error: !valid
      ? 'This course could not be found.'
      : error,

    retry: () =>
      setAttempt((current) => current + 1),

    isDemo: id === 'demo',
  }
}