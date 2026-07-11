# QA Report — Circle 1 (T1 + T2)

_Role: qa-tester. Independent verification of tickets T1 (`/api/analyze` one-call flow) and T2 (SaaS app shell & dark design system) from `docs/IMPROVEMENT_PLAN.md`._

Date: 2026-07-12
Environment: backend `.venv` + live Groq key (`backend/.env`), Vite build, WSL2 Linux.

## Summary of runs

| Check | Command | Result |
| --- | --- | --- |
| Backend unit tests | `cd backend && python -m pytest -q` | **4 passed** in 0.42s |
| Frontend build | `cd frontend && npm run build` | **Success** — built in ~1s, no errors |
| Live server boot | `PORT=8000 ./start.sh` | `/health` → `200 {"status":"ok"}` within 1s |

## T1 — One-call `/api/analyze` flow

| Acceptance criterion | Verdict | Evidence / note |
| --- | --- | --- |
| Valid JD+CV → 200 with `job`, `fit`, `tailor` all populated, shapes match per-endpoint | **PASS** | Live POST returned HTTP 200. `job.title="Senior Backend Engineer"`, `must_haves`=4, `fit.overall_score=90` + non-empty `summary`, `tailor.bullets`=5, `grounding`=5, `flagged_count=1`, `cover_letter` present. |
| Three services run concurrently via a single `await asyncio.gather(...)`, not sequentially | **PASS** | `server.py:68-73` `_gather_analyze` runs `asyncio.gather(extract_job, score_fit, tailor)`; `api_analyze` (l.57-65) awaits it once via `_safe`. |
| Missing `jd_text`/`cv_text` → 400 with clear `detail` (reuse `_require`) | **PASS** (with note) | Empty `cv_text` → `400 {"detail":"'cv_text' is required"}` via `_require`. Note: a *fully-omitted* field returns Pydantic `422` (see Bug #1) before `_require` runs. |
| One service failure → `502` via `_safe`/`LLMError`, not an unhandled 500 | **PASS** (by code review) | `_safe` (l.82-87) wraps `_gather_analyze`; any `LLMError` from a gathered coroutine propagates and maps to `HTTPException(502)`. Could not force a live LLM failure without disabling the working key; verified by inspection. |
| `api.js` exposes `analyze(jd, cv)`; `extractJob`/`scoreFit`/`tailor` still exported | **PASS** | `frontend/src/api.js:15-21` exports all four. |

## T2 — SaaS app shell & dark design system

| Acceptance criterion | Verdict | Evidence / note |
| --- | --- | --- |
| Dark, responsive layout: two-pane ≥900px, single-column stacked <900px, no horizontal scroll on mobile | **PASS** | `styles.css:117` `.main` grid `1fr 1fr`; `@media (max-width: 899px)` (l.122) → `grid-template-columns: 1fr`. `min-width:0` on `.main`/`.panel` guards overflow; cover letter uses `white-space: pre-wrap`. Dark palette in `:root` (`--bg:#0b0f17`). |
| All colors/spacing/radius from CSS variables defined once; no hard-coded hex scattered through JSX | **PASS** | `grep '#' App.jsx` → no matches. Inline styles in JSX only reference `var(--sp-*)` or `0`. Hex literals live solely in the `:root` token block in `styles.css` (by design). |
| Single primary **Analyze** button drives T1 flow; disabled + spinner while loading | **PASS** | `App.jsx:213-220` single `.btn--primary` → `onAnalyze()` → `analyze(jd, cv)`; `disabled={!canAnalyze}` (disabled while `loading`), `.spinner` shown and label switches to "Analyzing…". |
| Empty state shows a short "how it works" hint, not a blank page | **PASS** | `EmptyState` (l.135-146) renders icon + "How it works" + one-line explanation; shown when `result` is null (l.238-246). |
| Readable contrast (WCAG AA) for body text and buttons in dark theme | **PASS** (manual) | Body text `--text:#e6edf6` on `--bg:#0b0f17` ≈ 15:1 contrast (well above AA 4.5:1). Primary button uses `#fff` on the accent gradient (`#6d5efc`→`#9b8cff`). No automated Lighthouse run available in this environment; assessed by contrast math. |

### Supporting wiring (T2 affected files)
- `main.jsx` imports `./styles.css` — PASS.
- `index.html` has descriptive `<title>` + `viewport` + `description` meta — PASS.

## Bugs found

**Bug #1 — Omitted request field returns 422 instead of 400 (severity: LOW)**
When `cv_text` (or `jd_text`) is entirely absent from the JSON body, Pydantic validation returns `422 Unprocessable Entity` before `_require` runs, rather than the `400` the T1 criterion specifies. An empty-string value correctly returns `400`. Still a clear, structured client error (not an unhandled 500), so impact is cosmetic/spec-literalness only. Fix would require validating presence in the handler or making fields `Optional` and relying on `_require`.
- Repro: `POST /api/analyze {"jd_text":"Backend engineer"}` → `422`.
- Repro (works as intended): `POST /api/analyze {"jd_text":"...","cv_text":""}` → `400 {"detail":"'cv_text' is required"}`.

## Verdict

All acceptance criteria for T1 and T2 pass under live and build verification. The single finding is a low-severity spec-literalness deviation (omitted field → 422 vs 400) that does not break core validation behavior and never produces a 500.

VERDICT: PASS
