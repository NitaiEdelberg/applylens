// What the last run actually did: which stages ran, how long each took, how
// many tokens they burned, and which model answered. Renders nothing when the
// response has no trace (saved analyses from before tracing existed).
//
// The bars are proportional to wall-clock time, and stages that ran
// concurrently look concurrent, because that is the first thing you want to
// know when a run feels slow.

const STAGE_LABEL = {
  extract: 'Read the job',
  fit: 'Score the fit',
  tailor: 'Write + fact-check',
  retrieve: 'Retrieve history',
}

function tokens(stage) {
  return (stage.calls || []).reduce(
    (sum, c) => sum + (c.prompt_tokens || 0) + (c.completion_tokens || 0),
    0
  )
}

export default function RunTrace({ trace }) {
  if (!trace || !trace.stages || trace.stages.length === 0) return null

  const totals = trace.totals || {}
  const longest = Math.max(...trace.stages.map((s) => s.ms || 0), 1)
  const models = totals.models || []

  return (
    <details className="card runtrace">
      <summary className="runtrace__summary">
        <span className="runtrace__title">
          {trace.cached ? 'Served from cache' : 'This run'}
        </span>
        <span className="runtrace__facts">
          <span>{(trace.total_ms / 1000).toFixed(1)}s</span>
          {!trace.cached && totals.llm_calls > 0 && (
            <span>
              {totals.llm_calls} model {totals.llm_calls === 1 ? 'call' : 'calls'}
            </span>
          )}
          {!trace.cached && (totals.prompt_tokens || totals.completion_tokens) > 0 && (
            <span>
              {(totals.prompt_tokens + totals.completion_tokens).toLocaleString()} tokens
            </span>
          )}
          {typeof totals.cost_usd === 'number' && (
            <span>${totals.cost_usd.toFixed(4)}</span>
          )}
        </span>
      </summary>

      {trace.cached ? (
        <p className="runtrace__note">
          Identical job and CV to a recent run, so the answer came from memory
          instead of four fresh model calls.
        </p>
      ) : (
        <ul className="runtrace__stages">
          {trace.stages.map((stage) => (
            <li className="runtrace__stage" key={stage.name}>
              <span className="runtrace__name">
                {STAGE_LABEL[stage.name] || stage.name}
              </span>
              <span className="runtrace__bar" aria-hidden="true">
                <span
                  className={`runtrace__fill${stage.error ? ' runtrace__fill--error' : ''}`}
                  style={{ width: `${Math.max(2, ((stage.ms || 0) / longest) * 100)}%` }}
                />
              </span>
              <span className="runtrace__ms">{(stage.ms / 1000).toFixed(1)}s</span>
              <span className="runtrace__tokens">
                {stage.error ? stage.error : tokens(stage) ? `${tokens(stage).toLocaleString()} tok` : '—'}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="runtrace__foot">
        Request <code>{trace.request_id}</code>
        {models.length > 0 && <> · answered by {models.join(', ')}</>}
      </p>
    </details>
  )
}
