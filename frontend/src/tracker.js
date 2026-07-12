// Application tracker persistence (localStorage). Versioned key + defensive
// parsing so corrupt or old-schema data never crashes the app.
const KEY = 'applylens.tracker.v1'

export const STATUSES = ['applied', 'interviewing', 'offer', 'rejected']
export const STATUS_LABEL = {
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
}

export function loadApps() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return [] // corrupt/unavailable storage → start empty, never crash
  }
}

function persist(apps) {
  try {
    localStorage.setItem(KEY, JSON.stringify(apps))
  } catch {
    // storage full or blocked (private mode) — fail silently
  }
}

export function saveApp({ title, company, result }) {
  const record = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: title || 'Untitled role',
    company: company || '',
    status: 'applied',
    savedAt: new Date().toISOString(),
    score: result && result.fit ? result.fit.overall_score : null,
    flagged: result && result.tailor ? result.tailor.flagged_count : 0,
    result,
  }
  const next = [record, ...loadApps()]
  persist(next)
  return next
}

export function updateStatus(id, status) {
  const next = loadApps().map((a) => (a.id === id ? { ...a, status } : a))
  persist(next)
  return next
}

export function deleteApp(id) {
  const next = loadApps().filter((a) => a.id !== id)
  persist(next)
  return next
}
