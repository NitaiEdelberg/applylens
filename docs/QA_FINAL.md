# ApplyLens — Final QA Pass (T1–T7)

_Date: 2026-07-12 · Role: QA/Test · Scope: whole improvement effort, report-only._

## Automated gates

| Gate | Result |
| --- | --- |
| `frontend && npm run build` | **PASS** — vite build clean, 38 modules, no errors/warnings (index 160.89 kB / 51.93 kB gzip) |
| `backend && pytest -q` | **PASS** — 4 passed in 0.58s |
| Live backend boot + `/health` | **PASS** — healthy in 1s, `{"status":"ok"}` |
| Live `POST /api/analyze` (valid JD+CV) | **PASS** — HTTP 200 in ~1.9s; shape `{job, fit, tailor}` matches `AnalyzeResponse` and frontend consumers |

### Live /api/analyze verification
- Top keys: `job, fit, tailor`. Sub-shapes match schemas exactly.
- `job`: title, seniority, must_haves, nice_to_haves, stack.
- `fit`: overall_score(=80), matched(`{requirement, evidence}`), partial, missing, summary.
- `tailor`: bullets(6), grounding(6 — **zips 1:1 with bullets**), flagged_count(4).
- `grounding[i]`: `{statement, supported, evidence, issue}` — verified entries carry `evidence`, flagged carry `issue`. Matches `GroundingCheck`.
- Error paths: blank `cv_text` → **400** `{"detail":"'cv_text' is required"}`; absent field → 422 (Pydantic); malformed `{}` → 422. No 500s.
- Realistic matched pair already produced **4 flagged bullets** → red "Not supported" cards are screenshot-ready (T3 criterion met live).

## Per-ticket review

| Ticket | Area | Verdict |
| --- | --- | --- |
| **T1** | `/api/analyze` concurrency + errors (server.py) | **PASS** |
| **T2** | Design system / responsive shell (styles.css, App.jsx) | **PASS** |
| **T3** | GuardrailPanel (verified/flagged cards, evidence/reason, % meter, copy) | **PASS** |
| **T4** | FitGauge (ring bands, chips, empty states) | **PASS** |
| **T5** | api.js cold-start (health ping, bounded retry, friendly errors) | **PASS** |
| **T6** | tracker.js + Tracker.jsx + App wiring | **PASS** |
| **T7** | TrustPanel + eval-results import + run_evals results.json emit | **PASS** |

### T1 — one-call analyze
- Single `await asyncio.gather(extract_job, score_fit, tailor)` in `_gather_analyze` (server.py:68-73) → concurrent, not sequential. ✓
- Wrapped in `_safe`, so one `LLMError` → 502, not unhandled 500. ✓
- `_require` returns 400 for blank fields; three legacy endpoints still present. ✓
- api.js exports `analyze` plus `extractJob/scoreFit/tailor`. ✓

### T2 — design system / shell
- All palette/spacing/radius tokens defined once in `:root` (styles.css:6-35). **Zero hex in JSX** (grep clean). ✓
- Only inline styles in JSX are dynamic/layout (`meter__fill` width, one `marginTop: var(--sp-4)`, one `marginBottom:0`) — no colors. ✓
- Two-pane grid `1fr 1fr` ≥900px, single column `@media (max-width:899px)` (styles.css:117,122-124). ✓
- Primary Analyze button with disabled + spinner; styled EmptyState "How it works". ✓

### T3 — guardrail hero
- Cards colored by `grounding[i].supported`; absent entry falls back to verified styling (`verdictFor`, GuardrailPanel.jsx:5-14). ✓
- Verified shows `evidence`, flagged shows `issue`, with sensible fallback labels. ✓
- Summary `N bullets · X verified · Y flagged` + % meter with progressbar a11y. ✓
- "Copy selected bullets" copies only included (supported-by-default) bullets; exclude toggle works; button disabled at 0. ✓
- `included` state resets via `useEffect([verdicts])` on every new payload — no stale state between analyses. ✓

### T4 — fit gauge
- Band boundaries correct: 49→danger, 50→warn, 74→warn, 75→success (`bandTone`, FitGauge.jsx:5-9). ✓
- Score clamped 0–100, proportional arc via dasharray/offset, numeric centered. ✓
- Matched=green/evidence, partial=amber/note, missing=red; chips expand on click + title tooltip. ✓
- Empty arrays render a "None" chip, not empty box/stray comma. ✓

### T5 — cold-start UX
- `checkHealth` never throws (returns false); pinged on load → warm/cold dot. ✓
- `postWithRetry` bounded retry (MAX_RETRIES=2, backoff [1500,4000]); 502/503/504 + AbortError + TypeError treated transient. ✓
- `friendlyMessage` strips raw "Failed to fetch"; onRetry fires the "Waking up the analysis server… ~40s" panel. ✓
- No raw stack/`TypeError` can reach the user. ✓

### T6 — tracker
- Versioned key `applylens.tracker.v1`; `loadApps`/`persist` wrapped in try/catch → corrupt/blocked storage returns `[]`, never crashes. ✓
- `saveApp` stores title, company, status, savedAt, score, flagged, and full `result`. ✓
- `updateStatus`/`deleteApp` persist; Tracker.jsx renders title/company/score/flagged/date + status select + delete. ✓
- `onOpen` sets `result = app.result` and switches to Analyze view — **no network/LLM call**. ✓
- App wiring: Analyze/Tracker tabs, save bar, `apps` initialised from `loadApps`. ✓

### T7 — trust panel
- `run_evals.py` writes `evals/results.json` with accuracy/precision/recall/n/generated_at AND copies to `frontend/src/eval-results.json` (run_evals.py:55-72). ✓
- `results.json` present: n=17, matches `dataset.jsonl` (17 rows). ✓
- TrustPanel `hasMetrics` guard → stat tiles when present, neutral "measured by the eval harness" fallback when absent; no invented numbers. ✓
- Honest "Measured on a small labeled set" copy + pointer to `evals/`. TrustBadge in header. ✓

## Regression / integration sweep
- Imports: all component imports resolve; backend service imports load. ✓
- No `console.log`/`debugger`, no TODO/FIXME in shipped src. ✓
- List keys present everywhere (Chips, gcards, fitchips, Tracker by `a.id`). ✓
- `flagged_count` consistent: backend counts `supported==False`; GuardrailPanel recomputes from same grounding; Tracker badge reads `tailor.flagged_count` — all derive from one array. ✓
- State reset between analyses verified via GuardrailPanel `useEffect` + fresh props on re-render / onOpen. ✓

## Issues (all non-blocking)

| # | Sev | Ticket | File:line | Note |
| --- | --- | --- | --- | --- |
| 1 | LOW | T1 | backend/src/server.py:60-61 | Truly-*absent* `jd_text`/`cv_text` returns **422** (Pydantic) rather than the literal "400" in the acceptance criterion; `_require` only fires for present-but-blank strings (which do return 400). Both are clean 4xx with detail — no 500 — so functionally acceptable; noted for spec-literalness only. |
| 2 | INFO | T2 | frontend/src/styles.css:230,254,516,597 | Four hex literals remain outside `:root` (`#fff` button/spinner text, `#4ee08c` gradient stop, `#f4a1ab` light danger). None are in JSX — the stated criterion ("no hex scattered through JSX") is fully met; purely cosmetic. |
| 3 | INFO | T7 | frontend/src/components/TrustPanel.jsx:1 | `eval-results.json` is a static import; runtime fallback handles empty/malformed content, but a physically-missing file would fail the build rather than show the neutral state. File is committed, so no impact in practice. |

No functional bugs, broken imports, undefined-prop crashes, key warnings, or cross-analysis state leaks found.

---

VERDICT: PASS
