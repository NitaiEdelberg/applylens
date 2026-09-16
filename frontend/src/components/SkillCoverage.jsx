// Deterministic coverage signal — a non-LLM second opinion shown
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

  const disputed = new Set(skillMatch.disputed || [])
  const notAssessed = skillMatch.not_assessed || []
  // A requirement the two signals disagree about is shown as unresolved rather
  // than in the same colour as the ones they agree on: on hand-labelled data
  // the agreements were right 19/19 and the disagreements 3/16.
  const covered = (skillMatch.covered || []).filter((c) => !disputed.has(c.requirement))
  const missing = (skillMatch.missing || []).filter((m) => !disputed.has(m))
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
            Deterministic, no model involved. Checks which requirement terms your
            CV actually evidences, counting a named tool as evidence for its
            category (Snowflake covers "cloud warehouse"). Hover a chip to see
            what matched. Amber means this signal and the AI score disagree, so
            neither is claiming to be right; traits like "team player" are not
            judged at all, because no CV can prove them.
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
                title={
                  (c.matched || []).length
                    ? (c.matched || [])
                        .map((m) => `${m.term} ← ${m.evidence}`)
                        .join(', ')
                    : `score ${c.score}`
                }
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
            {[...disputed].map((d, i) => (
              <span
                className="fitchip fitchip--warn"
                key={`d-${i}`}
                title="This signal and the AI fit score disagree here, so neither verdict is shown."
              >
                <span className="fitchip__dot" aria-hidden="true" />
                <span className="fitchip__label">{d}</span>
              </span>
            ))}
          </div>

          {notAssessed.length > 0 && (
            <p className="skillcov__declined">
              Not judged, because a CV cannot show them:{' '}
              {notAssessed.join(' · ')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
