// Deterministic TF-IDF keyword-coverage signal — a non-LLM second opinion shown
// next to the LLM Fit score. Renders a compact coverage ring plus covered
// (green) / missing (red) requirement chips. Renders nothing if the signal is
// absent (older saved analyses won't have it), so the layout never breaks.

// Same banding as FitGauge so the two signals read consistently.
function bandTone(score) {
  if (score >= 75) return 'success'
  if (score >= 50) return 'warn'
  return 'danger'
}

// Compact ring (smaller sibling of FitGauge's Ring), reusing the shared
// fitgauge__arc/track tone styles.
function CoverageRing({ score }) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0))
  const tone = bandTone(clamped)
  const size = 92
  const stroke = 9
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - clamped / 100)

  return (
    <div
      className="skillcov__ring"
      role="img"
      aria-label={`Keyword coverage ${clamped} out of 100`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          className="fitgauge__track"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          className={`fitgauge__arc fitgauge__arc--${tone}`}
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="skillcov__center">
        <span className={`skillcov__num fitgauge__num--${tone}`}>{clamped}</span>
        <span className="skillcov__unit">%</span>
      </div>
    </div>
  )
}

export default function SkillCoverage({ skillMatch }) {
  if (!skillMatch) return null

  const covered = skillMatch.covered || []
  const missing = skillMatch.missing || []
  const total = covered.length + missing.length

  return (
    <div className="card skillcov">
      <div className="skillcov__top">
        <CoverageRing score={skillMatch.coverage_score} />
        <div className="skillcov__summary">
          <h3 className="card__title skillcov__title">Keyword coverage (ML)</h3>
          <p className="skillcov__text">
            {total > 0 ? (
              <>
                <strong>{covered.length}</strong> of <strong>{total}</strong>{' '}
                requirements covered by your CV.
              </>
            ) : (
              'No extracted requirements to match against.'
            )}
          </p>
          <p className="skillcov__caption">
            Deterministic TF-IDF keyword coverage — a non-LLM second opinion next
            to the AI fit score.
          </p>
        </div>
      </div>

      {total > 0 && (
        <div className="skillcov__groups">
          <div className="fit-chips">
            {covered.map((c, i) => (
              <span
                className="fitchip fitchip--success"
                key={`c-${i}`}
                title={`similarity ${c.score}`}
              >
                <span className="fitchip__dot" aria-hidden="true" />
                <span className="fitchip__label">{c.requirement}</span>
              </span>
            ))}
            {missing.map((m, i) => (
              <span className="fitchip fitchip--danger" key={`m-${i}`}>
                <span className="fitchip__dot" aria-hidden="true" />
                <span className="fitchip__label">{m}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
