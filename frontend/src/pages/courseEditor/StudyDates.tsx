import { addDays, dateKey } from '../../shared/format'
import type { CourseConfig } from '../course/types'

export default function StudyDates({ value, onChange, disabled = false, errors = {} }: {
  value: Pick<CourseConfig, 'startDate' | 'deadline' | 'earlyDays'>
  onChange: (next: Pick<CourseConfig, 'startDate' | 'deadline' | 'earlyDays'>) => void
  disabled?: boolean; errors?: Record<string, string>
}) {
  return <div className="form-grid">
    <label className="field"><span>Start learning on *</span><input id="course-startDate" type="date" required min={dateKey()} disabled={disabled} value={value.startDate || ''} onChange={e => onChange({ ...value, startDate: e.target.value })} />{errors.startDate && <span className="field-error" role="alert">{errors.startDate}</span>}</label>
    <label className="field"><span>Finish learning by *</span><input id="course-deadline" type="date" required min={dateKey()} disabled={disabled} value={value.deadline} onChange={e => onChange({ ...value, deadline: e.target.value })} />{errors.deadline && <span className="field-error" role="alert">{errors.deadline}</span>}</label>
    <label className="field"><span>Finish early by (days)</span><input id="course-earlyDays" type="number" min={0} max={365} step={1} disabled={disabled} value={value.earlyDays} onChange={e => onChange({ ...value, earlyDays: e.target.value === '' ? 0 : Number(e.target.value) })} />{errors.earlyDays && <span className="field-error" role="alert">{errors.earlyDays}</span>}<small className="muted">Default: 0 days.</small></label>
    {value.deadline && <p className="muted small">Planned finish: {addDays(value.deadline, -value.earlyDays)}</p>}
  </div>
}
