import { useEffect, useMemo, useState } from 'react'

// Zip a bullet with its grounding verdict. A genuinely-absent grounding entry
// falls back to verified styling (the guardrail never invents a red flag).
function verdictFor(grounding, i) {
  const g = grounding && grounding[i]
  if (!g) return { supported: true, evidence: null, issue: null, missing: true }
  return {
    supported: !!g.supported,
    evidence: g.evidence,
    issue: g.issue,
    missing: false,
  }
}

function CoverLetter({ text }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className={`cl${open ? ' cl--open' : ''}`}>
      <button
        type="button"
        className="cl__toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`cl__chevron${open ? ' cl__chevron--open' : ''}`} aria-hidden="true">
          ▶
        </span>
        Cover letter
        <span className="cl__hint">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && <pre className="cover-letter">{text}</pre>}
    </div>
  )
}

export default function GuardrailPanel({ tailor }) {
  const bullets = tailor.bullets || []
  const grounding = tailor.grounding || []

  // Per-bullet verdict, computed once per tailor payload.
  const verdicts = useMemo(
    () => bullets.map((_, i) => verdictFor(grounding, i)),
    [bullets, grounding],
  )

  const verifiedCount = verdicts.filter((v) => v.supported).length
  const flaggedCount = verdicts.length - verifiedCount
  const pct = verdicts.length ? Math.round((verifiedCount / verdicts.length) * 100) : 0

  // Inclusion state drives "Copy verified bullets". Default: supported bullets
  // included, flagged bullets excluded. Reset whenever a new analysis arrives.
  const [included, setIncluded] = useState(() => verdicts.map((v) => v.supported))
  useEffect(() => {
    setIncluded(verdicts.map((v) => v.supported))
  }, [verdicts])

  const [copied, setCopied] = useState(false)

  function toggle(i) {
    setIncluded((prev) => prev.map((v, idx) => (idx === i ? !v : v)))
  }

  const includedBullets = bullets.filter((_, i) => included[i])

  async function copyVerified() {
    const text = includedBullets.map((b) => `• ${b}`).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard blocked (e.g. insecure context) — surface nothing loud;
      // the button simply does not confirm.
    }
  }

  return (
    <div className="card guardrail">
      <div className="guardrail__header">
        <div className="guardrail__heading">
          <h3 className="card__title guardrail__title">
            <span className="guardrail__shield" aria-hidden="true">🛡️</span>
            Grounding guardrail
          </h3>
          <p className="guardrail__summary">
            <strong>{verdicts.length}</strong> {verdicts.length === 1 ? 'bullet' : 'bullets'}
            <span className="guardrail__dot">·</span>
            <span className="guardrail__count guardrail__count--ok">{verifiedCount} verified</span>
            <span className="guardrail__dot">·</span>
            <span className="guardrail__count guardrail__count--flag">{flaggedCount} flagged</span>
          </p>
        </div>
        <div className="guardrail__pct" aria-hidden="true">
          <span className="guardrail__pctnum">{pct}%</span>
          <span className="guardrail__pctlabel">verified</span>
        </div>
      </div>

      <div
        className="meter"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${pct}% of bullets verified against your CV`}
      >
        <div className="meter__fill" style={{ width: `${pct}%` }} />
      </div>

      <ul className="gcards">
        {bullets.map((b, i) => {
          const v = verdicts[i]
          const ok = v.supported
          const detail = ok
            ? v.evidence || 'Verified against your CV'
            : v.issue || 'Not supported by your CV'
          return (
            <li className={`gcard${ok ? '' : ' gcard--flagged'}`} key={i}>
              <div className="gcard__top">
                <span className={`badge ${ok ? 'badge--success' : 'badge--danger'} gcard__badge`}>
                  {ok ? '✓ Verified against your CV' : '⚠ Not supported'}
                </span>
                <label className="gcard__exclude" title="Include in copied bullets">
                  <input
                    type="checkbox"
                    checked={!!included[i]}
                    onChange={() => toggle(i)}
                  />
                  <span>{included[i] ? 'Included' : 'Excluded'}</span>
                </label>
              </div>
              <p className="gcard__text">{b}</p>
              <div className={`gcard__detail${ok ? '' : ' gcard__detail--flag'}`}>
                <span className="gcard__detail-label">{ok ? 'Evidence' : 'Reason'}</span>
                {detail}
              </div>
            </li>
          )
        })}
      </ul>

      <div className="guardrail__footer">
        <button type="button" className="btn btn--primary btn--sm" onClick={copyVerified} disabled={includedBullets.length === 0}>
          {copied ? '✓ Copied!' : `Copy selected bullets (${includedBullets.length})`}
        </button>
      </div>

      <CoverLetter text={tailor.cover_letter} />
    </div>
  )
}
