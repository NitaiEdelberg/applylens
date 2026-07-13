import { useEffect, useRef, useState } from 'react'
import {
  analyze,
  checkHealth,
  parseResume,
  cloudListApps,
  cloudSaveApp,
  cloudUpdateStatus,
  cloudDeleteApp,
  cloudSearchApps,
} from './api.js'
import GuardrailPanel from './components/GuardrailPanel.jsx'
import FitGauge from './components/FitGauge.jsx'
import SkillCoverage from './components/SkillCoverage.jsx'
import Tracker from './components/Tracker.jsx'
import TrustPanel, { TrustBadge } from './components/TrustPanel.jsx'
import AuthPanel from './components/AuthPanel.jsx'
import Footer from './components/Footer.jsx'
import { loadApps, saveApp, updateStatus, deleteApp } from './tracker.js'

// Auth token + email persist in localStorage. Accounts are OPTIONAL: when a
// token is present the Tracker syncs via the API (cross-device); when absent it
// uses the anonymous localStorage tracker exactly as before.
const TOKEN_KEY = 'applylens.auth.token'
const EMAIL_KEY = 'applylens.auth.email'

// Cloud tracker records carry `payload` (the saved analysis); the localStorage
// tracker + Tracker.jsx expect it under `result`. Normalize so the UI is
// identical regardless of source (Tracker.onOpen reads `.result`).
function normalizeCloudApp(a) {
  return {
    id: a.id,
    title: a.title,
    company: a.company || '',
    status: a.status,
    score: a.score,
    flagged: a.flagged || 0,
    savedAt: a.savedAt,
    result: a.payload,
  }
}

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

// Small note shown when RAG pulled relevant experiences from the optional
// career-history corpus. Renders nothing unless retrieval was actually used.
function RagNote({ rag }) {
  if (!rag || !rag.used) return null
  const chunks = rag.chunks || []
  if (chunks.length === 0) return null
  const src = rag.source === 'gemini' ? 'Gemini embeddings' : 'local TF-IDF'
  return (
    <div className="card rag" aria-label="Retrieved career history">
      <p className="rag__head">
        🔎 RAG: pulled {chunks.length} relevant experience
        {chunks.length === 1 ? '' : 's'} from your career history (via {src}) —
        tailoring is grounded against these plus your CV.
      </p>
      <ul className="rag__list">
        {chunks.map((c, i) => (
          <li className="rag__snippet" key={i}>{c}</li>
        ))}
      </ul>
    </div>
  )
}

export default function App() {
  const [jd, setJd] = useState('')
  const [cv, setCv] = useState('')
  const [career, setCareer] = useState('')
  const [careerOpen, setCareerOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [waking, setWaking] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  // The jd/cv that produced the current `result`. Empty for a re-opened saved
  // analysis (inputs aren't persisted) so "Fix this bullet" hides gracefully.
  const [analyzedJd, setAnalyzedJd] = useState('')
  const [analyzedCv, setAnalyzedCv] = useState('')
  const [serverStatus, setServerStatus] = useState('unknown')

  // Resume-upload state. The parsed text fills the same `cv` field, so the rest
  // of the flow is unchanged and the text stays editable / pasteable.
  const [uploading, setUploading] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // Auth state. Token/email are read once from localStorage; the tracker data
  // source (cloud vs. localStorage) switches on `token`.
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '')
  const [email, setEmail] = useState(() => localStorage.getItem(EMAIL_KEY) || '')
  const [authOpen, setAuthOpen] = useState(false)

  // Tracker state. Anonymous → localStorage (tracker.js); signed-in → cloud API.
  const [view, setView] = useState('analyze')
  const [apps, setApps] = useState(() =>
    localStorage.getItem(TOKEN_KEY) ? [] : loadApps(),
  )
  const [company, setCompany] = useState('')
  const [justSaved, setJustSaved] = useState(false)
  const [trackerError, setTrackerError] = useState('')
  // Count of local apps we can offer to import on first login (0 = no offer).
  const [importOffer, setImportOffer] = useState(0)

  // Tracker search. Signed-in users hit GET /api/tracker/search (debounced,
  // Bearer) — Elasticsearch-backed when configured, DB substring otherwise.
  // Anonymous users filter their localStorage apps client-side by the same
  // title/company substring. `searchResults` is null when not actively
  // searching (show the full `apps`), or the cloud result array otherwise.
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)

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

  // Load the tracker from the right source whenever auth changes: cloud when
  // signed in, localStorage when anonymous. A failed/expired token degrades to
  // an empty cloud list with a friendly message — never a crash.
  useEffect(() => {
    let alive = true
    if (token) {
      cloudListApps(token)
        .then((list) => {
          if (!alive) return
          setApps(list.map(normalizeCloudApp))
          setTrackerError('')
        })
        .catch((e) => {
          if (!alive) return
          setApps([])
          setTrackerError(String(e.message || e))
        })
    } else {
      setApps(loadApps())
    }
    return () => {
      alive = false
    }
  }, [token])

  // Signed-in search: debounce the query and hit the server. Empty query clears
  // results (falls back to showing the full `apps`). Anonymous users don't run
  // this effect — they filter localStorage client-side in `visibleApps` below.
  useEffect(() => {
    if (!token) {
      setSearchResults(null)
      return
    }
    const q = search.trim()
    if (!q) {
      setSearchResults(null)
      setSearching(false)
      return
    }
    let alive = true
    setSearching(true)
    const handle = setTimeout(() => {
      cloudSearchApps(token, q)
        .then((list) => {
          if (!alive) return
          setSearchResults(list.map(normalizeCloudApp))
          setTrackerError('')
        })
        .catch((e) => {
          if (!alive) return
          setSearchResults([])
          setTrackerError(String(e.message || e))
        })
        .finally(() => {
          if (alive) setSearching(false)
        })
    }, 300)
    return () => {
      alive = false
      clearTimeout(handle)
    }
  }, [search, token])

  async function refreshCloud() {
    try {
      const list = await cloudListApps(token)
      setApps(list.map(normalizeCloudApp))
      setTrackerError('')
    } catch (e) {
      setTrackerError(String(e.message || e))
    }
  }

  function onAuthed({ token: tok, email: em }) {
    localStorage.setItem(TOKEN_KEY, tok)
    localStorage.setItem(EMAIL_KEY, em || '')
    setToken(tok)
    setEmail(em || '')
    setAuthOpen(false)
    setView('tracker')
    // Offer a one-time import of any anonymous localStorage apps.
    const local = loadApps()
    setImportOffer(local.length)
  }

  function onSignOut() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(EMAIL_KEY)
    setToken('')
    setEmail('')
    setImportOffer(0)
    setTrackerError('')
    setSearch('')
    setSearchResults(null)
    // The token effect will reload the anonymous localStorage apps.
  }

  // One-time: copy anonymous localStorage apps into the signed-in account so
  // nobody loses their existing tracker. Local records are left intact.
  async function onImportLocal() {
    const local = loadApps()
    try {
      for (const a of local) {
        await cloudSaveApp(token, {
          title: a.title,
          company: a.company,
          score: a.score,
          flagged: a.flagged,
          payload: a.result,
        })
      }
      setImportOffer(0)
      await refreshCloud()
    } catch (e) {
      setTrackerError(String(e.message || e))
    }
  }

  async function onAnalyze() {
    setError('')
    setWaking(false)
    setJustSaved(false)
    setLoading(true)
    try {
      const data = await analyze(jd, cv, career.trim(), {
        // Fires on the first transient failure — the server is likely cold.
        onRetry: () => {
          setWaking(true)
          setServerStatus('waking')
        },
      })
      setResult(data)
      setAnalyzedJd(jd)
      setAnalyzedCv(cv)
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

  async function onFilePick(file) {
    if (!file) return
    setUploadError('')
    setUploadName(file.name)
    setUploading(true)
    try {
      const text = await parseResume(file)
      setCv(text)
    } catch (e) {
      setUploadError(String(e.message || e))
      setUploadName('')
    } finally {
      setUploading(false)
    }
  }

  function onFileInputChange(e) {
    const file = e.target.files && e.target.files[0]
    onFilePick(file)
    // Reset so picking the same file again re-triggers change.
    e.target.value = ''
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    if (uploading) return
    const file = e.dataTransfer.files && e.dataTransfer.files[0]
    onFilePick(file)
  }

  function loadExample() {
    setJd(SAMPLE_JD)
    setCv(SAMPLE_CV)
  }

  async function onSave() {
    if (!result) return
    const title = (result.job && result.job.title) || 'Untitled role'
    if (token) {
      const score = result.fit ? result.fit.overall_score : null
      const flagged = result.tailor ? result.tailor.flagged_count : 0
      try {
        await cloudSaveApp(token, { title, company, score, flagged, payload: result })
        await refreshCloud()
      } catch (e) {
        setTrackerError(String(e.message || e))
        return
      }
    } else {
      setApps(saveApp({ title, company, result }))
    }
    setCompany('')
    setJustSaved(true)
    setTimeout(() => setJustSaved(false), 1800)
  }

  async function onStatusChange(id, status) {
    if (token) {
      setApps((prev) => prev.map((a) => (a.id === id ? { ...a, status } : a)))
      try {
        await cloudUpdateStatus(token, id, status)
      } catch (e) {
        setTrackerError(String(e.message || e))
        refreshCloud() // reconcile UI with the server on failure
      }
    } else {
      setApps(updateStatus(id, status))
    }
  }

  async function onDelete(id) {
    if (token) {
      try {
        await cloudDeleteApp(token, id)
        setApps((prev) => prev.filter((a) => a.id !== id))
      } catch (e) {
        setTrackerError(String(e.message || e))
      }
    } else {
      setApps(deleteApp(id))
    }
  }

  // Re-open a saved analysis with no network/LLM call.
  function onOpen(app) {
    setResult(app.result)
    // Saved analyses don't persist the raw jd/cv — clear so Fix hides.
    setAnalyzedJd('')
    setAnalyzedCv('')
    setError('')
    setView('analyze')
  }

  const canAnalyze = jd.trim() && cv.trim() && !loading

  // The apps to render in the tracker, after search. Signed-in users get the
  // server's results (`searchResults`); anonymous users filter localStorage by
  // the same title/company substring, client-side. Empty query → full list.
  const trimmedSearch = search.trim()
  const searchActive = trimmedSearch.length > 0
  let visibleApps = apps
  if (searchActive) {
    if (token) {
      visibleApps = searchResults || []
    } else {
      const needle = trimmedSearch.toLowerCase()
      visibleApps = apps.filter(
        (a) =>
          (a.title || '').toLowerCase().includes(needle) ||
          (a.company || '').toLowerCase().includes(needle),
      )
    }
  }

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
          {token ? (
            <div className="auth">
              <span className="auth__email" title={email}>{email}</span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={onSignOut}>
                Sign out
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setAuthOpen(true)}
            >
              Sign in to sync
            </button>
          )}
        </div>
      </header>

      {authOpen && (
        <AuthPanel onClose={() => setAuthOpen(false)} onAuthed={onAuthed} />
      )}

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
                <div
                  className={`upload${dragOver ? ' upload--drag' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragOver(true)
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx"
                    className="upload__input"
                    onChange={onFileInputChange}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    disabled={uploading}
                    onClick={() => fileInputRef.current && fileInputRef.current.click()}
                  >
                    {uploading && <span className="spinner spinner--accent" aria-hidden="true" />}
                    {uploading ? 'Reading…' : 'Upload PDF/DOCX'}
                  </button>
                  <span className="upload__hint">
                    {uploadName ? uploadName : 'or drop a file here — or paste below'}
                  </span>
                </div>
                {uploadError && (
                  <div className="alert alert--error" role="alert">
                    {uploadError}
                  </div>
                )}
                <textarea
                  id="cv"
                  className="textarea"
                  value={cv}
                  onChange={(e) => setCv(e.target.value)}
                  placeholder="Paste your CV / experience…"
                />
              </div>
              <div className="field field--career">
                <button
                  type="button"
                  className="career__toggle"
                  aria-expanded={careerOpen}
                  onClick={() => setCareerOpen((v) => !v)}
                >
                  <span className="career__caret" aria-hidden="true">
                    {careerOpen ? '▾' : '▸'}
                  </span>
                  Career history (optional — deeper tailoring)
                  {!careerOpen && career.trim() ? ' ✓' : ''}
                </button>
                {careerOpen && (
                  <>
                    <p className="career__hint">
                      Paste a fuller background — extra roles, projects, a brag doc.
                      For each job we retrieve the most relevant pieces (RAG) and
                      tailor from them while keeping every bullet grounded.
                    </p>
                    <textarea
                      id="career"
                      className="textarea"
                      value={career}
                      onChange={(e) => setCareer(e.target.value)}
                      placeholder="Paste extra roles, projects, or a brag doc…"
                    />
                  </>
                )}
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
                <RagNote rag={result.rag} />
                <GuardrailPanel tailor={result.tailor} jdText={analyzedJd} cvText={analyzedCv} />
                <TrustPanel />
                <FitGauge fit={result.fit} />
                <SkillCoverage skillMatch={result.skill_match} />
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
            {token ? (
              <p className="tracker__source">
                ☁️ Synced to your account — available on any device.
              </p>
            ) : (
              <p className="tracker__source">
                🔒 Saved on this device only.{' '}
                <button type="button" className="linkbtn" onClick={() => setAuthOpen(true)}>
                  Sign in to sync across devices
                </button>
                .
              </p>
            )}
            {importOffer > 0 && (
              <div className="alert alert--info importbar" role="status">
                <span>
                  Import {importOffer} application{importOffer === 1 ? '' : 's'} from this
                  device into your account?
                </span>
                <div className="importbar__actions">
                  <button type="button" className="btn btn--primary btn--sm" onClick={onImportLocal}>
                    Import
                  </button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => setImportOffer(0)}>
                    Not now
                  </button>
                </div>
              </div>
            )}
            {trackerError && (
              <div className="alert alert--error" role="alert">
                {trackerError}
              </div>
            )}
            {apps.length > 0 && (
              <div className="tracker__search">
                <input
                  type="search"
                  className="input"
                  placeholder="Search your applications by title or company…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search applications"
                />
                {token && searchActive && (
                  <span className="tracker__searchhint" aria-live="polite">
                    {searching ? 'searching…' : 'search'}
                  </span>
                )}
              </div>
            )}
            {searchActive && visibleApps.length === 0 && !searching ? (
              <div className="empty">
                <div className="empty__icon" aria-hidden="true">🔍</div>
                <p className="empty__title">No matches</p>
                <p className="empty__hint">
                  No saved applications match “{trimmedSearch}”.
                </p>
              </div>
            ) : (
              <Tracker
                apps={visibleApps}
                onStatusChange={onStatusChange}
                onDelete={onDelete}
                onOpen={onOpen}
              />
            )}
          </section>
        </main>
      )}
      <Footer />
    </div>
  )
}
