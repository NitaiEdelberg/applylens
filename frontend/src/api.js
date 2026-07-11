// Same-origin in dev (Vite proxies /api to the backend). Override for a deployed backend.
const BASE = import.meta.env.VITE_API_URL || ''

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

export const extractJob = (jd_text) => post('/api/extract', { jd_text })
export const scoreFit = (jd_text, cv_text) => post('/api/fit', { jd_text, cv_text })
export const tailor = (jd_text, cv_text) => post('/api/tailor', { jd_text, cv_text })

// One-call flow: runs extract + fit + tailor concurrently on the server.
// Returns { job, fit, tailor }.
export const analyze = (jd_text, cv_text) => post('/api/analyze', { jd_text, cv_text })
