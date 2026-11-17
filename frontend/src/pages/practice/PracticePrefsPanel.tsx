import { useEffect, useState } from 'react'

import {
  listExamCases,
  type ExamCase,
} from '../course/api'

import type { PracticePrefs } from './api'

export type PracticePrefsDraft = {
  requirements: string
  difficulty: 'default' | 'easy' | 'medium' | 'hard'
  similar_to_cases: boolean
  preferred_kind: 'any' | 'mcq' | 'short'
  question_count: string
  case_document_ids: number[]
}

export function emptyPracticePrefs(): PracticePrefsDraft {
  return {
    requirements: '',
    difficulty: 'default',
    similar_to_cases: false,
    preferred_kind: 'any',
    question_count: '',
    case_document_ids: [],
  }
}

export function toPracticePrefs(
  draft: PracticePrefsDraft,
): PracticePrefs | null {
  const countRaw = draft.question_count.trim()
  const question_count =
    countRaw === ''
      ? null
      : Math.min(40, Math.max(1, Number.parseInt(countRaw, 10) || 0)) ||
        null
  const prefs: PracticePrefs = {
    requirements: draft.requirements.trim(),
    difficulty: draft.difficulty,
    similar_to_cases: draft.similar_to_cases,
    preferred_kind: draft.preferred_kind,
    question_count,
    case_document_ids: draft.case_document_ids,
  }
  if (
    !prefs.requirements &&
    prefs.difficulty === 'default' &&
    !prefs.similar_to_cases &&
    prefs.preferred_kind === 'any' &&
    prefs.question_count == null &&
    !prefs.case_document_ids?.length
  ) {
    return null
  }
  return prefs
}

export function PracticePrefsFields({
  courseId,
  value,
  onChange,
  active = true,
}: {
  courseId: number
  value: PracticePrefsDraft
  onChange: (next: PracticePrefsDraft) => void
  active?: boolean
}) {
  const [cases, setCases] = useState<ExamCase[]>([])
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    if (!active) return
    let cancelled = false
    setLoadError('')
    void listExamCases(courseId)
      .then((response) => {
        if (!cancelled) {
          setCases(
            response.cases.filter(
              (item) =>
                item.ingest_status === 'complete' &&
                item.usable_page_count > 0,
            ),
          )
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCases([])
          setLoadError('Could not load exam cases for this course.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [courseId, active])

  return (
    <div className="practice-prefs-body stack">
      <p className="muted small">
        Optional. Leave blank fields to keep the usual mastery path; these
        only guide question style.
      </p>

      <label className="stack">
        <span>Requirements</span>
        <textarea
          rows={3}
          maxLength={2000}
          value={value.requirements}
          onChange={(event) =>
            onChange({
              ...value,
              requirements: event.target.value,
            })
          }
          placeholder="Optional free-form guidance for question style"
        />
      </label>

      <label className="stack">
        <span>Difficulty</span>
        <select
          className="cp-select"
          value={value.difficulty}
          onChange={(event) =>
            onChange({
              ...value,
              difficulty: event.target
                .value as PracticePrefsDraft['difficulty'],
            })
          }
        >
          <option value="default">Default</option>
          <option value="easy">Easy</option>
          <option value="medium">Medium</option>
          <option value="hard">Hard</option>
        </select>
      </label>

      <label className="stack">
        <span>Preferred question style</span>
        <select
          className="cp-select"
          value={value.preferred_kind}
          onChange={(event) =>
            onChange({
              ...value,
              preferred_kind: event.target
                .value as PracticePrefsDraft['preferred_kind'],
            })
          }
        >
          <option value="any">Any (mastery path decides)</option>
          <option value="mcq">Lean toward multiple choice</option>
          <option value="short">Lean toward short answer</option>
        </select>
      </label>

      <label className="stack">
        <span>Soft quiz length hint</span>
        <input
          type="number"
          min={1}
          max={40}
          value={value.question_count}
          onChange={(event) =>
            onChange({
              ...value,
              question_count: event.target.value,
            })
          }
          placeholder="Optional, e.g. 10"
        />
      </label>

      <label className="practice-prefs-check">
        <input
          type="checkbox"
          checked={value.similar_to_cases}
          onChange={(event) => {
            const similar_to_cases = event.target.checked
            onChange({
              ...value,
              similar_to_cases,
              case_document_ids: similar_to_cases
                ? value.case_document_ids
                : [],
            })
          }}
        />
        <span>Match exam-case style</span>
      </label>

      {value.similar_to_cases && (
        <fieldset className="practice-prefs-cases">
          <legend>Exam cases</legend>
          {loadError && <p className="muted small">{loadError}</p>}
          {!loadError && cases.length === 0 && (
            <p className="muted small">
              No ready exam cases yet. Upload them on the Exam cases tab.
            </p>
          )}
          {cases.map((item) => {
            const checked = value.case_document_ids.includes(item.id)
            return (
              <label key={item.id} className="practice-prefs-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...value.case_document_ids, item.id]
                      : value.case_document_ids.filter(
                          (id) => id !== item.id,
                        )
                    onChange({
                      ...value,
                      case_document_ids: next,
                    })
                  }}
                />
                <span>{item.filename}</span>
              </label>
            )
          })}
          <p className="muted small">
            Leave all unchecked to use every ready exam case.
          </p>
        </fieldset>
      )}
    </div>
  )
}
