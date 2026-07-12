import results from '../eval-results.json'

const hasMetrics = results && typeof results.accuracy === 'number'

function pct(x) {
  return typeof x === 'number' ? `${Math.round(x * 100)}%` : '—'
}

// Compact header badge — always-visible credibility signal.
export function TrustBadge() {
  if (!hasMetrics) return null
  return (
    <span
      className="trustbadge"
      title={`Guardrail graded on a labeled eval set of ${results.n} statements`}
    >
      <span className="trustbadge__dot" aria-hidden="true" />
      Guardrail {pct(results.accuracy)} accurate
    </span>
  )
}

// Fuller panel with stat tiles, shown beside the guardrail results.
export default function TrustPanel() {
  if (!hasMetrics) {
    return (
      <div className="card trust">
        <p className="trust__note">
          Guardrail accuracy is measured by the eval harness in <code>evals/</code>.
        </p>
      </div>
    )
  }
  return (
    <div className="card trust">
      <div className="trust__head">
        <h3 className="card__title">🛡️ Measured guardrail accuracy</h3>
        <span className="trust__n">n = {results.n} labeled statements</span>
      </div>
      <div className="trust__tiles">
        <div className="tile">
          <span className="tile__num">{pct(results.accuracy)}</span>
          <span className="tile__label">Accuracy</span>
        </div>
        <div className="tile">
          <span className="tile__num">{pct(results.recall)}</span>
          <span className="tile__label">Fabrication recall</span>
        </div>
        <div className="tile">
          <span className="tile__num">{pct(results.precision)}</span>
          <span className="tile__label">Fabrication precision</span>
        </div>
      </div>
      <p className="trust__note">
        Measured on a small labeled set — the guardrail is graded on how reliably it
        flags fabricated resume claims. A raw chat gives you vibes; this gives you a
        number. See <code>evals/</code> for the harness.
      </p>
    </div>
  )
}
