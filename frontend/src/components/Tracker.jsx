import { STATUSES, STATUS_LABEL } from '../tracker.js'

// The saved-applications view. Purely presentational — all persistence lives in
// tracker.js and state is owned by App. Re-opening a record replays its stored
// analysis with no network/LLM call.
export default function Tracker({ apps, onStatusChange, onDelete, onOpen }) {
  if (!apps.length) {
    return (
      <div className="empty">
        <div className="empty__icon" aria-hidden="true">🗂️</div>
        <p className="empty__title">No saved applications yet</p>
        <p className="empty__hint">
          Analyze a job, then “Save to tracker” to keep it here and move it
          applied → interviewing → offer.
        </p>
      </div>
    )
  }

  return (
    <div className="tracker">
      {apps.map((a) => (
        <div className="trk" key={a.id}>
          <button
            type="button"
            className="trk__main"
            onClick={() => onOpen(a)}
            title="Open this saved analysis"
          >
            <span className="trk__title">{a.title}</span>
            <span className="trk__company">{a.company || '—'}</span>
            <span className="trk__meta">
              {a.score != null && (
                <span className="trk__score">Fit {a.score}</span>
              )}
              {a.flagged > 0 && (
                <span className="badge badge--danger">{a.flagged} flagged</span>
              )}
              <span className="trk__date">
                {new Date(a.savedAt).toLocaleDateString()}
              </span>
            </span>
          </button>
          <div className="trk__actions">
            <select
              className="trk__status"
              value={a.status}
              data-status={a.status}
              onChange={(e) => onStatusChange(a.id, e.target.value)}
              aria-label="Application status"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="trk__del"
              title="Delete"
              aria-label="Delete application"
              onClick={() => onDelete(a.id)}
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
