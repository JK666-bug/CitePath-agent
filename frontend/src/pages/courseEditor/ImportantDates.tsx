import { useEffect, useId, useRef } from 'react'
import { CalendarDays, Plus, Trash2 } from 'lucide-react'
import type { CalendarDate } from './noteCalendar'
import './importantDates.css'

export default function ImportantDates({
  value,
  onChange,
  disabled = false,
  onFind,
}: {
  value: CalendarDate[]
  onChange: (items: CalendarDate[]) => void
  disabled?: boolean
  onFind?: () => void
}) {
  const headingId = useId()
  const titleToFocus = useRef<number | null>(null)
  const list = useRef<HTMLUListElement>(null)

  useEffect(() => {
    if (titleToFocus.current === null) return
    list.current?.querySelectorAll<HTMLInputElement>('.calendar-dates-title input')[titleToFocus.current]?.focus()
    titleToFocus.current = null
  }, [value.length])

  function addDate() {
    titleToFocus.current = value.length
    onChange([...value, { title: '', date: '' }])
  }

  function changeDate(index: number, item: CalendarDate) {
    onChange(value.map((event, i) => i === index ? item : event))
  }

  return (
    <section className="calendar-dates" aria-labelledby={headingId}>
      <header className="calendar-dates-header">
        <div className="calendar-dates-heading">
          <span className="calendar-dates-icon" aria-hidden="true">
            <CalendarDays size={19} />
          </span>
          <div>
            <h3 id={headingId}>Calendar dates</h3>
            <p>Review detected dates before saving.</p>
          </div>
        </div>
        <div className="calendar-dates-actions">
          {onFind && (
            <button type="button" className="button secondary small" disabled={disabled} onClick={onFind}>
              Find dates in note
            </button>
          )}
          <button type="button" className="button secondary small calendar-dates-add" disabled={disabled} onClick={addDate}>
            <Plus size={15} aria-hidden="true" />
            Add date
          </button>
        </div>
      </header>

      {value.length ? (
        <div className="calendar-dates-table">
          <div className="calendar-dates-columns" aria-hidden="true">
            <span>Event</span>
            <span>Date</span>
          </div>
          <ul className="calendar-dates-list" ref={list}>
            {value.map((item, index) => (
              <li className="calendar-dates-row" key={index}>
                <div className="field calendar-dates-title">
                  <input
                    aria-label={`Event title ${index + 1}`}
                    placeholder="e.g. Final exam"
                    maxLength={255}
                    disabled={disabled}
                    value={item.title}
                    onChange={event => changeDate(index, { title: event.target.value, date: item.date })}
                  />
                </div>
                <div className="field calendar-dates-day">
                  <input
                    aria-label={item.title.trim() ? `Date for ${item.title}` : `Event date ${index + 1}`}
                    type="date"
                    disabled={disabled}
                    value={item.date}
                    onChange={event => changeDate(index, { title: item.title, date: event.target.value })}
                  />
                </div>
                <button
                  type="button"
                  className="icon-button calendar-dates-remove"
                  aria-label={item.title.trim() ? `Remove ${item.title}` : `Remove event ${index + 1}`}
                  title="Remove date"
                  disabled={disabled}
                  onClick={() => onChange(value.filter((_, i) => i !== index))}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="calendar-dates-empty">No calendar dates yet.</p>
      )}
    </section>
  )
}
