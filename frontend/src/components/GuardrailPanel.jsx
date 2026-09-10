import { useEffect, useMemo, useState } from 'react'
import { regenerateBullet, sendGroundingFeedback } from '../api.js'

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

// A cover letter is boilerplate + a few checkable claims. We ground ONLY the
// extracted factual self-claims (never the prose), so pleasantries like
// "I'm excited to apply" are never flagged.
function CoverVerdict({ grounding }) {
  if (!grounding) return null
  const total = grounding.length
  const flagged = grounding.filter((c) => !c.supported)
  if (total === 0) {
    return (
      <span className="cl__verdict cl__verdict--neutral" title="No verifiable experience claims to check">
        No verifiable claims
      </span>
    )
  }
  if (flagged.length === 0) {
    return (
      <span className="cl__verdict cl__verdict--ok">
        ✓ {total} experience {total === 1 ? 'claim' : 'claims'} verified
      </span>
    )
  }
  return (
    <span className="cl__verdict cl__verdict--flag">
      ⚠ {flagged.length} of {total} {total === 1 ? 'claim' : 'claims'} not supported
    </span>
  )
}

function CoverLetter({ text, grounding }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  const flagged = (grounding || []).filter((c) => !c.supported)
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
        <CoverVerdict grounding={grounding} />
        <span className="cl__hint">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && <pre className="cover-letter">{text}</pre>}
      {open && flagged.length > 0 && (
        <ul className="cl__flags">
          {flagged.map((c, i) => (
            <li className="cl__flag" key={i}>
              <span className="badge badge--danger cl__flag-badge">⚠ Not supported</span>
              <p className="cl__flag-claim">{c.statement}</p>
              <div className="gcard__detail gcard__detail--flag">
                <span className="gcard__detail-label">Reason</span>
                {c.issue || 'Not supported by your CV'}
              </div>
            </li>
          ))}
        </ul>
      )}
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
  // Verdicts the reader says are wrong. These are the rows worth having: the
  // guardrail's own mistakes, reported by the one person who knows the CV.
  const [disputed, setDisputed] = useState({})

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

  // A disputed verdict is stored, never applied: the badge stays as the
  // guardrail called it. Silently flipping it would hide the disagreement,
  // which is the only thing worth recording.
  async function dispute(i, item, modelSaidSupported) {
    setDisputed((d) => ({ ...d, [i]: true }))
    try {
      await sendGroundingFeedback({
        statement: item.text,
        cv_excerpt: (cvText || '').slice(0, 4000),
        model_supported: modelSaidSupported,
        human_supported: !modelSaidSupported,
        issue: item.issue || '',
      })
    } catch {
      // Losing a feedback row is not worth interrupting anyone over.
    }
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
              <div className="gcard__actions">
                {!ok && canFix && (
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm gcard__fix"
                    onClick={() => fixBullet(i)}
                    disabled={isFixing}
                  >
                    {isFixing && <span className="spinner spinner--accent" aria-hidden="true" />}
                    {isFixing ? 'Fixing…' : it.corrected ? 'Try fixing again' : 'Fix this bullet'}
                  </button>
                )}
                <button
                  type="button"
                  className="gcard__dispute"
                  onClick={() => dispute(i, it, ok)}
                  disabled={!!disputed[i]}
                  title="Tell me this verdict is wrong. It goes into the test set the guardrail is scored against."
                >
                  {disputed[i] ? '✓ Thanks — noted' : ok ? 'This is not in my CV' : 'My CV does say this'}
                </button>
                {fixError[i] && <span className="gcard__fix-error">{fixError[i]}</span>}
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

      <CoverLetter text={tailor.cover_letter} grounding={tailor.cover_grounding} />
    </div>
  )
}
