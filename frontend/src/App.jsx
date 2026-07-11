import { useState } from 'react'
import { analyze } from './api.js'

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

// --- modular result renderers (T3/T4 will upgrade these) ---

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

function FitCard({ fit }) {
  return (
    <div className="card">
      <h3 className="card__title">Fit score</h3>
      <div style={{ marginBottom: 'var(--sp-4)' }}>
        <span className="score">{fit.overall_score}</span>
        <span className="score__unit"> / 100</span>
      </div>
      {fit.summary && <p className="card__subtitle">{fit.summary}</p>}
      <div className="kv">
        <span className="kv__label">Matched</span>
        <Chips items={fit.matched.map((m) => m.requirement)} />
      </div>
      <div className="kv">
        <span className="kv__label">Partial</span>
        <Chips items={fit.partial.map((p) => p.requirement)} />
      </div>
      <div className="kv" style={{ marginBottom: 0 }}>
        <span className="kv__label">Missing</span>
        <Chips items={fit.missing} />
      </div>
    </div>
  )
}

function TailorCard({ tailor }) {
  const verified = tailor.bullets.length - tailor.flagged_count
  return (
    <div className="card">
      <h3 className="card__title">
        Tailored bullets{' '}
        <span className="badge badge--success">{verified} verified</span>
        {tailor.flagged_count > 0 && (
          <span className="badge badge--danger" style={{ marginLeft: 'var(--sp-2)' }}>
            {tailor.flagged_count} flagged
          </span>
        )}
      </h3>
      <ul className="bullets">
        {tailor.bullets.map((b, i) => {
          const g = tailor.grounding[i]
          const ok = !g || g.supported
          return (
            <li className={`bullet${ok ? '' : ' bullet--flagged'}`} key={i}>
              {b}
              {g && (
                <div className="bullet__meta">
                  {ok
                    ? g.evidence || 'Verified against your CV'
                    : g.issue || 'Not supported by your CV'}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {tailor.cover_letter && (
        <div className="kv" style={{ marginTop: 'var(--sp-4)', marginBottom: 0 }}>
          <span className="kv__label">Cover letter</span>
          <pre className="cover-letter">{tailor.cover_letter}</pre>
        </div>
      )}
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

export default function App() {
  const [jd, setJd] = useState('')
  const [cv, setCv] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  async function onAnalyze() {
    setError('')
    setLoading(true)
    try {
      const data = await analyze(jd, cv)
      setResult(data)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  function loadExample() {
    setJd(SAMPLE_JD)
    setCv(SAMPLE_CV)
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
        <div className="header__slot" aria-hidden="true">
          {/* trust badge slot (T7) */}
        </div>
      </header>

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
            {error && (
              <div className="alert alert--error" role="alert" style={{ marginTop: 'var(--sp-4)' }}>
                {error}
              </div>
            )}
          </div>
        </section>

        <section className="panel" aria-label="Results">
          {result ? (
            <>
              <JobCard job={result.job} />
              <FitCard fit={result.fit} />
              <TailorCard tailor={result.tailor} />
            </>
          ) : (
            <EmptyState />
          )}
        </section>
      </main>
    </div>
  )
}
