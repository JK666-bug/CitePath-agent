import type { MarkingFields } from '../feedback'

export default function MarkingPoints({ rubric, rubric_hits, points_hit, points_total }: MarkingFields) {
  if (!rubric?.length) return null
  const matchesRecorded = Array.isArray(rubric_hits)
  return (
    <section className="stack marking-points">
      <h4>Marking points</h4>
      {typeof points_hit === 'number' && typeof points_total === 'number' && (
        <p className="muted small">Recorded rubric result: {points_hit} of {points_total} points.</p>
      )}
      {!matchesRecorded && (
        <p className="muted small">Individual point matches were not recorded for this answer.</p>
      )}
      <ul className="stack">
        {rubric.map((point, index) => (
          <li key={point}>
            {matchesRecorded && (
              <span className="badge">{rubric_hits.includes(index) ? 'Matched' : 'Not matched'}</span>
            )}
            {' '}{point}
          </li>
        ))}
      </ul>
    </section>
  )
}
