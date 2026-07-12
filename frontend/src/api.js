// Same-origin in dev (Vite proxies /api and /health to the backend).
// Override for a deployed backend via VITE_API_URL.
const BASE = import.meta.env.VITE_API_URL || ''

// Free-tier Render sleeps; the first request can spend 30-60s waking the
// container. Tunables below keep the cold-start UX bounded and predictable.
const HEALTH_TIMEOUT = 4000 // a warm server answers /health near-instantly
const ANALYZE_TIMEOUT = 60000 // generous: covers wake + the LLM round-trips
const MAX_RETRIES = 2 // => up to 3 attempts total
const BACKOFF = [1500, 4000] // ms between attempts (increasing)

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

// fetch with an AbortController timeout. On timeout the promise rejects with an
// AbortError, which we treat as transient (a sleeping server that never replied).
async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(id)
  }
}

// Is this the kind of failure a cold / sleeping server produces, and therefore
// worth retrying? Network errors (TypeError "Failed to fetch"), aborts/timeouts,
// and gateway statuses (502/503/504) all qualify.
function isTransient(err) {
  if (!err) return false
  if (err.name === 'AbortError') return true // our timeout
  if (err.transientStatus) return true // 502/503/504 flagged below
  if (err instanceof TypeError) return true // network / "Failed to fetch"
  return false
}

// Health check: resolves true only if /health answers ok within the timeout.
// Never throws — a sleeping or unreachable server simply resolves false.
export async function checkHealth(timeoutMs = HEALTH_TIMEOUT) {
  try {
    const res = await fetchWithTimeout(`${BASE}/health`, { method: 'GET' }, timeoutMs)
    return res.ok
  } catch {
    return false
  }
}

// POST with bounded retry/backoff. `onRetry(attempt, err)` fires before each
// retry so the UI can show a friendly "waking up" state. Always rejects with a
// human-readable Error — never a raw TypeError / stack.
async function postWithRetry(path, body, { onRetry } = {}) {
  let lastErr
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetchWithTimeout(
        `${BASE}${path}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
        ANALYZE_TIMEOUT,
      )

      // Gateway errors are the classic cold-start signature — mark transient.
      if (res.status === 502 || res.status === 503 || res.status === 504) {
        const e = new Error(`Server waking (${res.status})`)
        e.transientStatus = res.status
        throw e
      }

      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        // A real, non-transient application error (e.g. 400/500 with detail).
        throw new Error(data.detail || `Request failed (${res.status})`)
      }
      return data
    } catch (err) {
      lastErr = err
      if (!isTransient(err) || attempt === MAX_RETRIES) break
      if (onRetry) onRetry(attempt + 1, err)
      await sleep(BACKOFF[Math.min(attempt, BACKOFF.length - 1)])
    }
  }

  // Translate whatever went wrong into a friendly, final message.
  throw new Error(friendlyMessage(lastErr))
}

function friendlyMessage(err) {
  if (isTransient(err)) {
    return "We couldn't reach the analysis server. It may still be waking up on the free tier — please try again in a moment."
  }
  // Application-level error carrying a server-provided detail.
  const msg = err && err.message ? String(err.message) : ''
  if (msg && !/failed to fetch/i.test(msg)) return msg
  return 'Something went wrong analyzing this job. Please try again.'
}

async function post(path, body) {
  return postWithRetry(path, body)
}

export const extractJob = (jd_text) => post('/api/extract', { jd_text })
export const scoreFit = (jd_text, cv_text) => post('/api/fit', { jd_text, cv_text })
export const tailor = (jd_text, cv_text) => post('/api/tailor', { jd_text, cv_text })

// "Fix this bullet": regenerate one flagged bullet conditioned on its failure
// reason, then independently re-verify it. Returns { bullet, grounding }.
// Inherits postWithRetry cold-start retry/backoff + friendly errors.
export const regenerateBullet = (jd_text, cv_text, bullet, issue) =>
  postWithRetry('/api/regenerate-bullet', { jd_text, cv_text, bullet, issue: issue || '' })

// One-call flow: runs extract + fit + tailor concurrently on the server.
// Returns { job, fit, tailor }. `opts.onRetry` fires on transient failures so
// the UI can show a "waking up the server" state.
export const analyze = (jd_text, cv_text, opts = {}) =>
  postWithRetry('/api/analyze', { jd_text, cv_text }, opts)
