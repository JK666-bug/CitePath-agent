import StudyDates from './StudyDates'
import type { CourseConfig } from '../course/types'

export type CourseFormValue =
  CourseConfig & {
    name: string
  }

export default function CourseForm({
  value,
  onChange,
  errors,
  disabled,
}: {
  value: CourseFormValue
  onChange: (
    value: CourseFormValue,
  ) => void
  errors: Record<string, string>
  disabled: boolean
}) {
  function error(key: string) {
    return errors[key] ? (
      <span
        id={`course-${key}-error`}
        className="field-error"
        role="alert"
      >
        {errors[key]}
      </span>
    ) : null
  }

  return (
    <div className="form-grid">
      <label className="field full">
        <span>Course name *</span>

        <input
          id="course-name"
          value={value.name}
          maxLength={255}
          disabled={disabled}
          aria-invalid={
            Boolean(errors.name)
          }
          aria-describedby={
            errors.name
              ? 'course-name-error'
              : undefined
          }
          onChange={(event) =>
            onChange({
              ...value,
              name: event.target.value,
            })
          }
          placeholder="e.g. Algorithms & Data Structures"
        />

        {error('name')}
      </label>

      <div className="full"><StudyDates value={value} onChange={(next) => onChange({ ...value, ...next })} errors={errors} disabled={disabled} /></div>
      <label className="field full">
        <span>
          Course note and calendar dates
        </span>

        <textarea
          id="course-note"
          rows={4}
          value={value.note}
          disabled={disabled}
          maxLength={9000}
          onChange={(event) =>
            onChange({
              ...value,
              note: event.target.value,
            })
          }
          placeholder="Optional note, e.g. Final exam on Dec 11 or 12月11日期末考试."
        />

        {error('note')}
      </label>
    </div>
  )
}