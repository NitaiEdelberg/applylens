import { useEffect, useMemo, useState } from 'react'
import { regenerateBullet } from '../api.js'

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

export default function GuardrailPanel({ tailor, jdText, cvText }) {
  const bullets = tailor.bullets || []
  const grounding = tailor.grounding || []

  // Fix requires the original inputs. A saved (tracker) analysis re-opened from
  // localStorage has no jd/cv in state — in that case Fix is hidden gracefully.
  const canFix = !!(jdText && jdText.trim() && cvText && cvText.trim())

  // Per-bullet items, seeded once per tailor payload. These are mutable: the
  // "Fix this bullet" loop swaps a card's text + verdict in place so the badge,
  // reason/evidence, meter %, and counts all re-render from this state.
  const initialItems = useMemo(
    () =>
      bullets.map((text, i) => {
        const v = verdictFor(grounding, i)
        return {
          text,
          supported: v.supported,
          evidence: v.evidence,
          issue: v.issue,
          missing: v.missing,
          corrected: false, // set true once regenerated
          prevIssue: null, // the reason it was flagged before the fix
        }
      }),
    [bullets, grounding],
  )

  const [items, setItems] = useState(initialItems)
  // Inclusion state drives "Copy selected bullets". Default: supported bullets
  // included, flagged excluded. Reset whenever a new analysis arrives.
  const [included, setIncluded] = useState(() => initialItems.map((it) => it.supported))
  const [fixing, setFixing] = useState(() => initialItems.map(() => false))
  const [fixError, setFixError] = useState(() => initialItems.map(() => null))
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setItems(initialItems)
    setIncluded(initialItems.map((it) => it.supported))
    setFixing(initialItems.map(() => false))
    setFixError(initialItems.map(() => null))
  }, [initialItems])

  const verifiedCount = items.filter((it) => it.supported).length
  const flaggedCount = items.length - verifiedCount
  const pct = items.length ? Math.round((verifiedCount / items.length) * 100) : 0

  function toggle(i) {
    setIncluded((prev) => prev.map((v, idx) => (idx === i ? !v : v)))
  }

  async function fixBullet(i) {
    if (!canFix) return
    setFixError((prev) => prev.map((e, idx) => (idx === i ? null : e)))
    setFixing((prev) => prev.map((v, idx) => (idx === i ? true : v)))
    try {
      const item = items[i]
      const res = await regenerateBullet(jdText, cvText, item.text, item.issue || '')
      const g = res.grounding || {}
      const supported = !!g.supported
      const prevIssue = item.issue || 'Not supported by your CV'
      setItems((prev) =>
        prev.map((it, idx) =>
          idx === i
            ? {
                ...it,
                text: res.bullet || it.text,
                supported,
                evidence: g.evidence,
                issue: g.issue,
                missing: false,
                corrected: true,
                prevIssue,
              }
            : it,
        ),
      )
      // A newly-verified regenerated bullet is eligible for copy by default.
      if (supported) {
        setIncluded((prev) => prev.map((v, idx) => (idx === i ? true : v)))
      }
    } catch (e) {
      const msg = e && e.message ? String(e.message) : 'Could not fix this bullet. Please try again.'
      setFixError((prev) => prev.map((val, idx) => (idx === i ? msg : val)))
    } finally {
      setFixing((prev) => prev.map((v, idx) => (idx === i ? false : v)))
    }
  }

  const includedBullets = items.filter((_, i) => included[i]).map((it) => it.text)

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
            <strong>{items.length}</strong> {items.length === 1 ? 'bullet' : 'bullets'}
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
        {items.map((it, i) => {
          const ok = it.supported
          const detail = ok
            ? it.evidence || 'Verified against your CV'
            : it.issue || 'Not supported by your CV'
          const isFixing = fixing[i]
          return (
            <li
              className={`gcard${ok ? '' : ' gcard--flagged'}${it.corrected ? ' gcard--corrected' : ''}`}
              key={i}
            >
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
              <p className="gcard__text">{it.text}</p>
              {it.corrected && ok && (
                <div className="gcard__corrected">
                  <span className="gcard__corrected-tag">↺ Corrected</span>
                  <span className="gcard__corrected-was">was flagged: {it.prevIssue}</span>
                </div>
              )}
              <div className={`gcard__detail${ok ? '' : ' gcard__detail--flag'}`}>
                <span className="gcard__detail-label">{ok ? 'Evidence' : 'Reason'}</span>
                {detail}
              </div>
              {!ok && canFix && (
                <div className="gcard__actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm gcard__fix"
                    onClick={() => fixBullet(i)}
                    disabled={isFixing}
                  >
                    {isFixing && <span className="spinner spinner--accent" aria-hidden="true" />}
                    {isFixing ? 'Fixing…' : it.corrected ? 'Try fixing again' : 'Fix this bullet'}
                  </button>
                  {fixError[i] && <span className="gcard__fix-error">{fixError[i]}</span>}
                </div>
              )}
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
