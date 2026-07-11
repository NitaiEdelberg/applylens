import { useState } from 'react'
import { extractJob, scoreFit, tailor } from './api.js'

const box = { width: '100%', minHeight: 160, padding: 10, fontFamily: 'inherit', fontSize: 14, boxSizing: 'border-box' }
const btn = { padding: '8px 14px', marginRight: 8, cursor: 'pointer' }
const card = { border: '1px solid #ddd', borderRadius: 8, padding: 16, marginTop: 16 }

export default function App() {
  const [jd, setJd] = useState('')
  const [cv, setCv] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const [job, setJob] = useState(null)
  const [fit, setFit] = useState(null)
  const [tailored, setTailored] = useState(null)

  async function run(name, fn) {
    setError(''); setLoading(name)
    try { return await fn() }
    catch (e) { setError(String(e.message || e)) }
    finally { setLoading('') }
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1>ApplyLens 🔎</h1>
      <p style={{ color: '#555' }}>
        Paste a job description and your CV. Extract requirements, score your fit,
        and generate <b>grounded</b> tailored bullets — with a guardrail that flags anything not backed by your CV.
      </p>

      <h3>Job description</h3>
      <textarea style={box} value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the job posting..." />
      <h3>Your CV</h3>
      <textarea style={box} value={cv} onChange={(e) => setCv(e.target.value)} placeholder="Paste your CV / experience..." />

      <div style={{ marginTop: 12 }}>
        <button style={btn} disabled={!!loading} onClick={() => run('extract', async () => setJob(await extractJob(jd)))}>Extract requirements</button>
        <button style={btn} disabled={!!loading} onClick={() => run('fit', async () => setFit(await scoreFit(jd, cv)))}>Score fit</button>
        <button style={btn} disabled={!!loading} onClick={() => run('tailor', async () => setTailored(await tailor(jd, cv)))}>Tailor (grounded)</button>
        {loading && <span> ⏳ {loading}…</span>}
      </div>
      {error && <p style={{ color: 'crimson' }}>⚠ {error}</p>}

      {job && (
        <div style={card}>
          <h3>{job.title || 'Requirements'} {job.seniority && <small>({job.seniority})</small>}</h3>
          <p><b>Must-haves:</b> {job.must_haves.join(', ') || '—'}</p>
          <p><b>Nice-to-haves:</b> {job.nice_to_haves.join(', ') || '—'}</p>
          <p><b>Stack:</b> {job.stack.join(', ') || '—'}</p>
        </div>
      )}

      {fit && (
        <div style={card}>
          <h3>Fit: {fit.overall_score}/100</h3>
          <p>{fit.summary}</p>
          <p style={{ color: 'green' }}><b>Matched:</b> {fit.matched.map((m) => m.requirement).join(', ') || '—'}</p>
          <p style={{ color: '#b8860b' }}><b>Partial:</b> {fit.partial.map((p) => p.requirement).join(', ') || '—'}</p>
          <p style={{ color: 'crimson' }}><b>Missing:</b> {fit.missing.join(', ') || '—'}</p>
        </div>
      )}

      {tailored && (
        <div style={card}>
          <h3>Tailored bullets {tailored.flagged_count > 0 && <span style={{ color: 'crimson' }}>({tailored.flagged_count} flagged)</span>}</h3>
          <ul>
            {tailored.bullets.map((b, i) => {
              const g = tailored.grounding[i]
              const ok = !g || g.supported
              return (
                <li key={i} style={{ color: ok ? 'inherit' : 'crimson', marginBottom: 6 }}>
                  {b} {!ok && <em title={g.issue || ''}>⚠ not supported by your CV</em>}
                </li>
              )
            })}
          </ul>
          <h4>Cover letter</h4>
          <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>{tailored.cover_letter}</pre>
        </div>
      )}
    </div>
  )
}
