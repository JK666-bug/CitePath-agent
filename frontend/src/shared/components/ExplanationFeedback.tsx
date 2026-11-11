import type { ExplanationFields } from '../feedback'

export default function ExplanationFeedback({
  explanation,
  explanation_status,
  explanation_error,
  explanation_attempts,
  busy = false,
  disabled = false,
  onRetry,
}: ExplanationFields & {
  explanation: string
  busy?: boolean
  disabled?: boolean
  onRetry?: () => void
}) {
  // Earlier reports stored a generic fallback when generation did not finish.
  const text = explanation.trim()
  const legacyPlaceholder = text === 'Review the cited page.'
  const status = explanation_status ?? (text && !legacyPlaceholder ? 'ready' : 'pending')
  if (status === 'not_required') return null
  if (status === 'ready') return <p>{explanation}</p>
  return (
    <div className="stack explanation-feedback" role="status">
      <p>
        <strong>{status === 'failed' ? 'Explanation unavailable.' : 'Explanation pending.'}</strong>
        {' '}Your recorded result is saved. Retrying the explanation keeps your score and round unchanged.
      </p>
      {explanation_error && <p className="muted small">{explanation_error}</p>}
      <div className="actions">
        {onRetry && (
          <button
            className="button small secondary"
            type="button"
            disabled={disabled || busy}
            onClick={onRetry}
          >
            {busy ? 'Retrying explanation…' : 'Retry explanation'}
          </button>
        )}
        {typeof explanation_attempts === 'number' && explanation_attempts > 0 && (
          <small className="muted">
            {explanation_attempts} generation {explanation_attempts === 1 ? 'attempt' : 'attempts'}
          </small>
        )}
      </div>
    </div>
  )
}
