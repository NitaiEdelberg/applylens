// Two things the user has a right to know about a run they just triggered:
// what was stripped from their CV before it left the server, and whether the
// job description they pasted was trying to talk to the model.
//
// The privacy line always shows when something was removed. The warning only
// shows when there is something to warn about — a banner that is always there
// is a banner nobody reads.

const KIND_LABEL = {
  email: 'email address',
  phone: 'phone number',
  url: 'social profile link',
  id: 'ID number',
  address: 'street address',
  dob: 'date of birth',
}

function describe(redacted) {
  const parts = Object.entries(redacted || {}).map(([kind, count]) => {
    const label = KIND_LABEL[kind] || kind
    return count > 1 ? `${count} ${label}s` : `your ${label}`
  })
  if (parts.length === 0) return null
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

export default function InputSafety({ screening, privacy }) {
  const removed = describe(privacy && privacy.redacted)
  const suspicious = screening && screening.suspicious
  if (!removed && !suspicious) return null

  return (
    <div className={`card safety${suspicious ? ' safety--warn' : ''}`}>
      {suspicious && (
        <div className="safety__block">
          <h3 className="safety__title">This job description talks to the AI</h3>
          <p className="safety__text">
            Text in the posting is written as an instruction to the model rather
            than as a description of a job. It was passed through as data and had
            no effect on your results, but it is worth knowing the posting
            contains it.
          </p>
          <ul className="safety__signals">
            {(screening.signals || []).map((s, i) => (
              <li key={i}>
                <q className="safety__match">{s.matched}</q>
                <span className="safety__why">
                  {s.why}
                  {s.source === 'jailbreak-api' ? ' · JailbreakAPI' : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {removed && (
        <p className="safety__privacy">
          🔒 {removed} {Object.keys(privacy.redacted).length > 1 ? 'were' : 'was'} removed
          from your CV before it was sent for analysis, and put back in the results
          afterwards.
        </p>
      )}

      {screening && screening.remote === 'unavailable' && suspicious && (
        <p className="safety__note">
          The second detector was asleep, so only the built-in checks ran.
        </p>
      )}
    </div>
  )
}
