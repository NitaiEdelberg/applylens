// Live log of a repair-agent run: every tool call as it happens, grouped per
// bullet, with what came back. The point is that the person can see the agent
// look for evidence, get refused by the verifier and narrow its claim, instead
// of a spinner followed by a verdict they have to take on trust.

const TOOL_LABEL = {
  search_cv: 'Search CV',
  search_career: 'Search career history',
  rewrite: 'Rewrite',
  verify: 'Verify',
  accept: 'Accept',
  drop: 'Drop',
}

const OUTCOME = {
  accepted: { label: 'Fixed and verified', cls: 'ok' },
  dropped: { label: 'Dropped: no evidence', cls: 'drop' },
  unresolved: { label: 'Left flagged', cls: 'flag' },
}

function argsText(tool, args = {}) {
  if (args.query) return `"${args.query}"`
  if (args.reason) return args.reason
  if (tool === 'rewrite') return args.use_evidence === false ? 'from the CV only' : 'using evidence found'
  if (args.text) return `"${args.text}"`
  return ''
}

function observationText(obs) {
  if (obs == null) return ''
  if (Array.isArray(obs)) return obs.join('  ·  ')
  if (typeof obs === 'object') {
    if (obs.supported === true) return `supported${obs.evidence ? `: ${obs.evidence}` : ''}`
    if (obs.supported === false) return `not supported${obs.issue ? `: ${obs.issue}` : ''}`
    return JSON.stringify(obs)
  }
  return String(obs)
}

export default function AgentRun({ events, bullets, running }) {
  if (!events.length) return null
  const done = events.find((e) => e.type === 'done')
  const error = events.find((e) => e.type === 'error')
  const byBullet = new Map()
  for (const e of events) {
    if (e.bullet === undefined) continue
    if (!byBullet.has(e.bullet)) byBullet.set(e.bullet, [])
    byBullet.get(e.bullet).push(e)
  }

  return (
    <div className="agentrun" aria-live="polite">
      <div className="agentrun__head">
        <span className="agentrun__title">Repair agent</span>
        {running && <span className="spinner spinner--accent" aria-hidden="true" />}
        {done && (
          <span className="agentrun__summary">
            {done.summary.accepted} fixed · {done.summary.dropped} dropped · {done.summary.unresolved} left flagged
            {' · '}{done.summary.steps} steps · {(done.summary.ms / 1000).toFixed(0)}s
            {done.summary.llm && done.summary.llm.llm_calls ? (
              <> · {done.summary.llm.llm_calls} model calls, {((done.summary.llm.prompt_tokens || 0) + (done.summary.llm.completion_tokens || 0)).toLocaleString()} tokens
                {done.summary.llm.rate_limited ? ` (${done.summary.llm.rate_limited} rate-limited retries)` : ''}</>
            ) : null}
          </span>
        )}
      </div>

      {[...byBullet.entries()].map(([i, evs]) => {
        const resolved = evs.find((e) => e.type === 'resolved')
        const outcome = resolved && OUTCOME[resolved.outcome]
        return (
          <div className="agentrun__bullet" key={i}>
            <div className="agentrun__bullet-head">
              <span className="agentrun__bullet-text">{bullets[i] || `Bullet ${i + 1}`}</span>
              {outcome && <span className={`agentrun__outcome agentrun__outcome--${outcome.cls}`}>{outcome.label}</span>}
            </div>
            <ol className="agentrun__steps">
              {evs.filter((e) => e.type === 'step' || e.type === 'wait').map((e, k) =>
                e.type === 'wait' ? (
                  <li className="agentrun__step agentrun__step--wait" key={k}>
                    <span className="agentrun__tool">Waiting {e.seconds}s</span>
                    <span className="agentrun__obs">{e.reason}</span>
                  </li>
                ) : (
                  <li className={`agentrun__step${e.ok ? '' : ' agentrun__step--miss'}`} key={k}>
                    <span className="agentrun__tool">{TOOL_LABEL[e.tool] || e.tool}</span>
                    <span className="agentrun__args">{argsText(e.tool, e.args)}</span>
                    <span className="agentrun__obs">{observationText(e.observation)}</span>
                    {e.thought && <span className="agentrun__thought">{e.thought}</span>}
                  </li>
                ),
              )}
            </ol>
            {resolved && resolved.outcome === 'unresolved' && resolved.reason && (
              <p className="agentrun__reason">{resolved.reason}</p>
            )}
          </div>
        )
      })}
      {error && <p className="agentrun__error">{error.message}</p>}
    </div>
  )
}
