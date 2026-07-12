import { useEffect, useState } from 'react'
import { analyze, checkHealth } from './api.js'
import GuardrailPanel from './components/GuardrailPanel.jsx'
import FitGauge from './components/FitGauge.jsx'
import Tracker from './components/Tracker.jsx'
import TrustPanel, { TrustBadge } from './components/TrustPanel.jsx'
import { loadApps, saveApp, updateStatus, deleteApp } from './tracker.js'

const SAMPLE_JD = `Senior Backend Engineer — Payments

We're hiring a backend engineer to own our payments platform. You will design and ship high-throughput APIs, work closely with product, and keep our ledger correct.

Must have:
- 5+ years building production backend services (Python or Go)
- Strong experience with PostgreSQL and schema design
- Built and operated REST APIs at scale
- Comfortable with async processing and message queues

Nice to have:
- Experience with Stripe or a payments provider
- Kubernetes / Docker in production
- Familiarity with event-driven architectures

Stack: Python, FastAPI, PostgreSQL, Kafka, Kubernetes, AWS`

const SAMPLE_CV = `Backend engineer with 6 years of experience building and operating production services.

- Designed and shipped REST APIs in Python (FastAPI) serving 2M requests/day
- Owned PostgreSQL schema design and query optimization for a billing system
- Built async job pipelines using Celery and RabbitMQ for invoice processing
- Deployed and monitored services on AWS with Docker
- Led migration of a monolith to event-driven microservices

Skills: Python, FastAPI, PostgreSQL, RabbitMQ, Docker, AWS, REST`

function Chips({ items, empty = 'None' }) {
  if (!items || items.length === 0) {
    return <span className="chip chip--muted">{empty}</span>
  }
  return (
    <div className="chips">
      {items.map((it, i) => (
        <span className="chip" key={i}>{it}</span>
      ))}
    </div>
  )
}

function JobCard({ job }) {
  return (
    <div className="card">
      <h3 className="card__title">
        {job.title || 'Requirements'}
        {job.seniority ? ` · ${job.seniority}` : ''}
      </h3>
      <div className="kv">
        <span className="kv__label">Must-haves</span>
        <Chips items={job.must_haves} />
      </div>
      <div className="kv">
        <span className="kv__label">Nice-to-haves</span>
        <Chips items={job.nice_to_haves} />
      </div>
      <div className="kv" style={{ marginBottom: 0 }}>
        <span className="kv__label">Stack</span>
        <Chips items={job.stack} />
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="empty">
      <div className="empty__icon" aria-hidden="true">🔎</div>
      <p className="empty__title">How it works</p>
      <p className="empty__hint">
        Paste a job + your CV → we extract requirements, score your fit, and tailor
        grounded bullets — flagging anything your CV doesn't support.
      </p>
    </div>
  )
}

// Small warm/cold indicator for the server. `status` is one of
// 'unknown' | 'warm' | 'cold' | 'waking'.
function StatusDot({ status }) {
  const label = {
    unknown: 'Checking server…',
    warm: 'Server ready',
    cold: 'Server asleep',
    waking: 'Waking server…',
  }[status]
  return (
    <span className={`status status--${status}`} title={label}>
      <span className="status__dot" aria-hidden="true" />
      <span className="status__text">{label}</span>
    </span>
  )
}

export default function App() {
  const [jd, setJd] = useState('')
  const [cv, setCv] = useState('')
  const [loading, setLoading] = useState(false)
  const [waking, setWaking] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [serverStatus, setServerStatus] = useState('unknown')

  // Tracker state (persisted in localStorage via tracker.js).
  const [view, setView] = useState('analyze')
  const [apps, setApps] = useState(loadApps)
  const [company, setCompany] = useState('')
  const [justSaved, setJustSaved] = useState(false)

  // Ping /health on load so the warm/cold dot reflects reality before the first
  // analyze. A sleeping / unreachable server resolves to 'cold' (never throws).
  useEffect(() => {
    let alive = true
    checkHealth().then((ok) => {
      if (alive) setServerStatus(ok ? 'warm' : 'cold')
    })
    return () => {
      alive = false
    }
  }, [])

  async function onAnalyze() {
    setError('')
    setWaking(false)
    setJustSaved(false)
    setLoading(true)
    try {
      const data = await analyze(jd, cv, {
        // Fires on the first transient failure — the server is likely cold.
        onRetry: () => {
          setWaking(true)
          setServerStatus('waking')
        },
      })
      setResult(data)
      setServerStatus('warm')
    } catch (e) {
      // api.js always throws a human-readable message here.
      setError(String(e.message || e))
      setServerStatus('cold')
    } finally {
      setLoading(false)
      setWaking(false)
    }
  }

  function loadExample() {
    setJd(SAMPLE_JD)
    setCv(SAMPLE_CV)
  }

  function onSave() {
    if (!result) return
    const title = (result.job && result.job.title) || 'Untitled role'
    setApps(saveApp({ title, company, result }))
    setCompany('')
    setJustSaved(true)
    setTimeout(() => setJustSaved(false), 1800)
  }

  function onStatusChange(id, status) {
    setApps(updateStatus(id, status))
  }

  function onDelete(id) {
    setApps(deleteApp(id))
  }

  // Re-open a saved analysis with no network/LLM call.
  function onOpen(app) {
    setResult(app.result)
    setError('')
    setView('analyze')
  }

  const canAnalyze = jd.trim() && cv.trim() && !loading

  return (
    <div className="app">
      <header className="header">
        <div className="header__brand">
          <h1 className="wordmark">ApplyLens</h1>
          <p className="tagline">
            Tailor your CV to any job — with a guardrail that never lets it lie.
          </p>
        </div>
        <div className="header__slot">
          <TrustBadge />
          <StatusDot status={serverStatus} />
        </div>
      </header>

      <nav className="tabs" aria-label="Views">
        <button
          type="button"
          className={`tab${view === 'analyze' ? ' tab--active' : ''}`}
          onClick={() => setView('analyze')}
        >
          Analyze
        </button>
        <button
          type="button"
          className={`tab${view === 'tracker' ? ' tab--active' : ''}`}
          onClick={() => setView('tracker')}
        >
          Tracker{apps.length ? ` (${apps.length})` : ''}
        </button>
      </nav>

      {view === 'analyze' ? (
        <main className="main">
          <section className="panel" aria-label="Inputs">
            <div className="card">
              <div className="field">
                <label className="field__label" htmlFor="jd">Job description</label>
                <textarea
                  id="jd"
                  className="textarea"
                  value={jd}
                  onChange={(e) => setJd(e.target.value)}
                  placeholder="Paste the job posting…"
                />
              </div>
              <div className="field">
                <label className="field__label" htmlFor="cv">Your CV</label>
                <textarea
                  id="cv"
                  className="textarea"
                  value={cv}
                  onChange={(e) => setCv(e.target.value)}
                  placeholder="Paste your CV / experience…"
                />
              </div>
              <div className="actions">
                <button
                  className="btn btn--primary"
                  disabled={!canAnalyze}
                  onClick={onAnalyze}
                >
                  {loading && <span className="spinner" aria-hidden="true" />}
                  {loading ? 'Analyzing…' : 'Analyze'}
                </button>
                <button
                  className="btn btn--ghost"
                  disabled={loading}
                  onClick={loadExample}
                >
                  Load example
                </button>
              </div>
              {loading && waking && (
                <div className="waking" role="status" aria-live="polite">
                  <span className="spinner spinner--accent" aria-hidden="true" />
                  <div className="waking__body">
                    <p className="waking__title">Waking up the analysis server…</p>
                    <p className="waking__hint">
                      Free tier — the first request can take ~40s while the server
                      spins up. Hang tight, this only happens once.
                    </p>
                  </div>
                </div>
              )}
              {!waking && error && (
                <div className="alert alert--error" role="alert" style={{ marginTop: 'var(--sp-4)' }}>
                  {error}
                </div>
              )}
            </div>
          </section>

          <section className="panel" aria-label="Results">
            {result ? (
              <>
                <GuardrailPanel tailor={result.tailor} />
                <TrustPanel />
                <FitGauge fit={result.fit} />
                <JobCard job={result.job} />
                <div className="card savebar">
                  <div className="field savebar__field">
                    <label className="field__label" htmlFor="company">Company (optional)</label>
                    <input
                      id="company"
                      className="input"
                      value={company}
                      onChange={(e) => setCompany(e.target.value)}
                      placeholder="e.g. Acme Inc."
                    />
                  </div>
                  <button type="button" className="btn btn--primary btn--sm" onClick={onSave}>
                    {justSaved ? '✓ Saved to tracker' : 'Save to tracker'}
                  </button>
                </div>
              </>
            ) : (
              <EmptyState />
            )}
          </section>
        </main>
      ) : (
        <main className="main main--single">
          <section className="panel" aria-label="Saved applications">
            <Tracker
              apps={apps}
              onStatusChange={onStatusChange}
              onDelete={onDelete}
              onOpen={onOpen}
            />
          </section>
        </main>
      )}
    </div>
  )
}
