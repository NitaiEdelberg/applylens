import { useState } from 'react'

// Band thresholds: red <50, amber 50-74, green >=75. Returns the tone token
// used for both the ring stroke and the score label.
function bandTone(score) {
  if (score >= 75) return 'success'
  if (score >= 50) return 'warn'
  return 'danger'
}

// Circular ring gauge. Score is clamped 0-100 and drawn as a proportional arc
// via stroke-dasharray/offset, with the numeric score centered.
function Ring({ score }) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0))
  const tone = bandTone(clamped)
  const size = 132
  const stroke = 12
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - clamped / 100)

  return (
    <div
      className="fitgauge__ring"
      role="img"
      aria-label={`Fit score ${clamped} out of 100`}
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
      <div className="fitgauge__center">
        <span className={`fitgauge__num fitgauge__num--${tone}`}>{clamped}</span>
        <span className="fitgauge__unit">/ 100</span>
      </div>
    </div>
  )
}

// A single requirement chip. Matched/partial chips carry detail (evidence/note)
// revealed on click (and via native hover tooltip); missing chips have none.
function ReqChip({ label, detail, tone }) {
  const [open, setOpen] = useState(false)
  const hasDetail = !!detail
  return (
    <>
      <button
        type="button"
        className={`fitchip fitchip--${tone}${open ? ' fitchip--open' : ''}`}
        onClick={() => hasDetail && setOpen((o) => !o)}
        title={hasDetail ? detail : undefined}
        aria-expanded={hasDetail ? open : undefined}
      >
        <span className="fitchip__dot" aria-hidden="true" />
        <span className="fitchip__label">{label}</span>
        {hasDetail && (
          <span className="fitchip__caret" aria-hidden="true">
            {open ? '−' : '+'}
          </span>
        )}
      </button>
      {open && hasDetail && (
        <div className={`fitchip__detail fitchip__detail--${tone}`}>{detail}</div>
      )}
    </>
  )
}

// A color-coded requirement group. Empty arrays render a graceful "None" chip
// rather than an empty box or stray comma.
function ReqGroup({ label, tone, items }) {
  const count = items.length
  return (
    <div className="fit-group">
      <div className="fit-group__head">
        <span className={`fit-group__key fit-group__key--${tone}`}>{label}</span>
        <span className="fit-group__count">{count}</span>
      </div>
      <div className="fit-chips">
        {count === 0 ? (
          <span className="fitchip fitchip--empty">None</span>
        ) : (
          items.map((it, i) => (
            <ReqChip key={i} label={it.label} detail={it.detail} tone={tone} />
          ))
        )}
      </div>
    </div>
  )
}

export default function FitGauge({ fit }) {
  const matched = (fit.matched || []).map((m) => ({
    label: m.requirement,
    detail: m.evidence,
  }))
  const partial = (fit.partial || []).map((p) => ({
    label: p.requirement,
    detail: p.note,
  }))
  const missing = (fit.missing || []).map((m) => ({
    label: m,
    detail: null,
  }))

  return (
    <div className="card fitgauge">
      <div className="fitgauge__top">
        <Ring score={fit.overall_score} />
        <div className="fitgauge__summary">
          <h3 className="card__title fitgauge__title">Fit score</h3>
          {fit.summary ? (
            <p className="fitgauge__text">{fit.summary}</p>
          ) : (
            <p className="fitgauge__text fitgauge__text--dim">
              No summary available for this analysis.
            </p>
          )}
        </div>
      </div>

      <div className="fit-groups">
        <ReqGroup label="Matched" tone="success" items={matched} />
        <ReqGroup label="Partial" tone="warn" items={partial} />
        <ReqGroup label="Missing" tone="danger" items={missing} />
      </div>
    </div>
  )
}
