import type { PracticeRoundResult } from './api'

export function PassThreshold({
  value,
  disabled = false,
  onChange,
}: {
  value: number
  disabled?: boolean
  onChange: (value: number) => void
}) {
  return (
    <label className="field">
      <span>Chapter pass mark for a new session</span>
      <select
        className="cp-select"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        <option value={0.7}>70%</option>
        <option value={0.8}>80% (default)</option>
        <option value={0.9}>90%</option>
      </select>
      <small className="muted">
        Fixed for both rounds. Resuming a session keeps its saved pass mark.
      </small>
    </label>
  )
}

export default function RoundSummary({
  rounds,
  threshold,
}: {
  rounds: PracticeRoundResult[]
  threshold: number
}) {
  return (
    <section className="panel stack">
      <h2>Round results</h2>
      <p className="muted small">
        Chapter pass mark: {Math.round(threshold * 100)}%.
        Each round is scored separately using the unrounded accuracy.
      </p>
      <div className="report-rounds">
        {rounds.map((round) => (
          <div key={round.round_number}>
            <small>Round {round.round_number} of 2</small>
            <strong>{Number(round.score.toFixed(1))}%</strong>
            <span className="badge">
              {round.passed ? 'Passed' : 'Not passed'}
            </span>
            <small>{round.correct_count} of {round.total} correct</small>
            {round.weak_concepts.length > 0 && (
              <p className="muted small">
                Review: {round.weak_concepts.join(' · ')}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

