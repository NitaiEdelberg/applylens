// "How it is measured": every number this app shows about itself, where it
// comes from, and the ones that did not go its way. Generated from the eval
// reports by evals/build_dashboard.py; CI fails if this page goes stale.
import data from '../eval-dashboard.json'

function fmt(h) {
  if (h.kind === 'pct') return `${Math.round(h.value * 1000) / 10}%`
  if (h.kind === 'num') return String(h.value)
  return h.of !== undefined ? `${h.value} / ${h.of}` : String(h.value)
}

function tone(h) {
  if (h.neutral) return '' // a comparison point, not a score of this system
  if (h.kind === 'pct') return h.value >= 0.9 ? 'ok' : h.value >= 0.6 ? 'mid' : 'bad'
  if (h.good === 'low') return h.value === 0 ? 'ok' : 'mid'
  return ''
}

function cell(v, col) {
  if (typeof v === 'number' && col === 'accuracy') return `${Math.round(v * 100)}%`
  return String(v)
}

export default function EvalsPage() {
  return (
    <section className="evals" aria-label="How it is measured">
      <div className="evals__intro card">
        <h2 className="evals__title">How it is measured</h2>
        <p>
          Every number ApplyLens shows about itself comes from a script in <code>evals/</code> that anyone
          can run, and CI checks these figures against those reports on every push. That includes the
          results that did not go its way, like the trained model that lost to a rule.
        </p>
      </div>
      {data.sections.map((s) => (
        <article className="card evals__section" key={s.id} id={`evals-${s.id}`}>
          <h3 className="card__title">{s.title}</h3>
          <p className="evals__question">{s.question}</p>
          <div className="evals__tiles">
            {s.headline.map((h) => (
              <div className={`tile evals__tile evals__tile--${tone(h)}`} key={h.label}>
                <span className="tile__num">{fmt(h)}</span>
                <span className="tile__label">{h.label}</span>
              </div>
            ))}
          </div>
          <p className="evals__how">{s.how}</p>
          {s.link && (
            <a className="evals__link" href={s.link.href} target="_blank" rel="noopener noreferrer">{s.link.label} ↗</a>
          )}
          {s.table && (
            <details className="evals__details">
              <summary>Breakdown by kind ({s.table.rows.length})</summary>
              <div className="evals__tablewrap">
                <table className="evals__table">
                  <thead><tr>{s.table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {s.table.rows.map((row) => (
                      <tr key={row[0]}>
                        {row.map((v, i) => <td key={i}>{cell(v, s.table.columns[i])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </article>
      ))}
    </section>
  )
}
