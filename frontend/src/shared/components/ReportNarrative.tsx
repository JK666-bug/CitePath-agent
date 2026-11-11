import type { ReportNarrative as Narrative } from '../feedback'
import { Sources } from './UI'

export default function ReportNarrative({ report, courseId }: { report: Narrative; courseId: string }) {
  const guidance = report.review_guidance ?? []
  if (!report.summary && !guidance.length && !report.round_summaries?.length) return null
  return (
    <section className="panel stack">
      <h2>Chapter summary</h2>
      {report.summary && <p>{report.summary}</p>}
      {report.round_summaries?.length ? (
        <ul>
          {report.round_summaries.map((text, index) => <li key={index}>{text}</li>)}
        </ul>
      ) : null}
      {guidance.length > 0 && (
        <div className="stack">
          <h3>Review guidance</h3>
          {guidance.map((item, index) => (
            <div className="stack" key={`${item.concept}-${index}`}>
              <h4>{item.concept}</h4>
              <p>{item.text}</p>
              <Sources sources={item.sources} courseId={courseId} />
            </div>
          ))}
        </div>
      )}
      {(report.feedback_pending_count ?? 0) > 0 && (
        <p className="muted small">
          {report.feedback_pending_count} wrong-answer {report.feedback_pending_count === 1 ? 'explanation needs' : 'explanations need'} another attempt.
          Use Retry explanation below. Recorded grades are unchanged.
        </p>
      )}
    </section>
  )
}
