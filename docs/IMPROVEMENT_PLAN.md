# ApplyLens — Improvement Plan

_PM plan to turn ApplyLens from "a thin Claude wrapper" into a visibly-engineered, resume-worthy SaaS product. Scoped for one focused developer pass. Free-tier only (Netlify + Render + browser localStorage; no new paid infra)._

---

## Positioning

**ApplyLens is a job-hunt workspace, not a chat box: it runs your CV against every job through a fabrication guardrail that labels each tailored bullet "verified against your CV" or "not supported" with the reason — a measured, repeatable, trackable workflow that a raw ChatGPT/Claude paste can never give you.**

Three things a chat window structurally cannot do, and ApplyLens does:
1. **Trust you can see** — an anti-fabrication guardrail fact-checks every generated bullet against your real CV and shows the verdict + evidence inline. Chat will happily invent "Led a team of 8 at Google"; ApplyLens flags it.
2. **A workflow across many jobs** — analyses are saved per job and tracked applied → interview → offer. Chat loses everything on refresh.
3. **Measured accuracy** — the guardrail's precision/recall come from a labeled eval harness and are shown in the UI as a credibility signal. Chat gives you vibes; ApplyLens gives you a number.

This is exactly the "applied-AI product judgment" story an **AI Solutions Engineer** interview wants: structured LLM I/O, a guardrail, evals, and a real UX around them.

---

## Prioritized Tickets

Priority key: **P0** = ships the core "it's a product" story; **P1** = high-value polish/features; **P2** = credibility signal.

---

### T1 — One-call `/api/analyze` flow (P0, enabler)

**Why.** Today the UI has three separate buttons that each fire a separate request — it feels like three demos bolted together, and it makes the redesigned single-screen "analyze this job" experience impossible. A product presents **one action** ("Analyze") and returns one coherent result. Also removes duplicate LLM round-trips (fit + tailor share the JD/CV). Resume/AI-SE value: shows API design and orchestration, not just three thin proxies.

**Scope.**
- **In:** New `POST /api/analyze` that takes `{jd_text, cv_text}` and returns a combined `AnalyzeResponse { job, fit, tailor }` by running `extract_job`, `score_fit`, and `tailor` concurrently (`asyncio.gather`). New `AnalyzeResponse` schema. New `analyze()` client function in `api.js`. Keep the existing three endpoints for backward-compat/evals.
- **Out:** No change to prompt logic in the service files. No streaming. No auth.

**Acceptance criteria.**
- `POST /api/analyze` with valid JD+CV returns `200` with all three sub-objects populated and matching the existing per-endpoint shapes.
- The three services run concurrently (single `await asyncio.gather(...)`), not sequentially.
- Missing `jd_text` or `cv_text` returns `400` with a clear `detail` (reuse `_require`).
- One LLM/service failure surfaces as `502` via existing `_safe`/`LLMError` handling, not an unhandled 500.
- `api.js` exposes `analyze(jd, cv)`; existing `extractJob`/`scoreFit`/`tailor` still exported.

**Affected files.** `backend/src/server.py`, `backend/src/schemas.py`, `frontend/src/api.js`, `README.md` (API table).

---

### T2 — SaaS app shell & dark design system (P0, enabler)

**Why.** Inline styles + three grey buttons on a white page is the single biggest reason it "looks like something you'd do in an afternoon." A real product has a consistent visual system: dark theme, spacing scale, cards, a header with the product mark, and a responsive two-pane layout (inputs → results). This is the frame every other ticket renders into. Resume/AI-SE value: "polished modern SaaS web app" is the founder's explicit ask.

**Scope.**
- **In:** Introduce a small design system: CSS variables (dark palette, accent, semantic success/warn/danger colors, radius, spacing) in a global stylesheet; replace App.jsx inline styles with classNames. App shell = sticky header (ApplyLens mark + one-line tagline + trust badge slot for T7), a responsive layout that is side-by-side on desktop and stacked on mobile (input panel + results panel), styled textareas, a primary **Analyze** button and a subtle secondary action. Loading and empty states styled (not raw text). Extract results as clean requirement lists.
- **Out:** No component library / Tailwind / CSS-in-JS dependency unless trivially free (prefer plain CSS or CSS modules). No routing library. No logo asset design beyond an emoji/wordmark. Score gauge, guardrail cards, chips, tracker are their own tickets (T3–T6) — this ticket only builds the container + basic result cards.

**Acceptance criteria.**
- App renders a dark-themed, responsive layout: two-pane ≥900px, single-column stacked <900px, no horizontal scroll on mobile.
- All colors/spacing/radius come from CSS variables defined once; no hard-coded hex scattered through JSX.
- A single primary **Analyze** button drives the T1 flow; disabled + spinner state while loading.
- Empty state (before first run) shows a short "how it works" hint, not a blank page.
- Lighthouse/manual check: readable contrast (WCAG AA) for body text and buttons in dark theme.

**Affected files.** `frontend/src/App.jsx`, new `frontend/src/styles.css` (or `App.css`), `frontend/src/main.jsx` (import stylesheet), `frontend/index.html` (title/meta).

---

### T3 — Grounding guardrail as the visual centerpiece (P0, HERO)

**Why.** The guardrail is the one thing chat can't do and the founder's non-negotiable differentiator — yet today it's a red `⚠` on a line of text. It must become the hero: each tailored bullet rendered as a card with an explicit **verdict**. Verified bullets show a green "Verified against your CV" badge + the supporting CV evidence; unsupported bullets show a red "Not supported" badge + the specific reason (`issue`) and a one-click "remove / don't use this" affordance. A prominent summary ("6 bullets · 5 verified · 1 flagged") sits at the top. This is the screenshot that sells the product. Resume/AI-SE value: demonstrates anti-hallucination guardrail design as a *user-facing trust feature*, not a hidden backend check.

**Scope.**
- **In:** A `GuardrailPanel` region rendering `tailor.bullets` zipped with `tailor.grounding`. Per bullet: color-coded card (green/red left border + badge), the bullet text, and — expanded or on hover — `evidence` (verified) or `issue` (flagged). A header summary bar with verified/flagged counts and a subtle progress meter of "% verified." Flagged bullets visually de-emphasized with an "exclude" toggle that removes them from a "copy clean bullets" action. A "Copy verified bullets" button that copies only supported bullets to clipboard. Cover letter shown in a styled collapsible block.
- **Out:** No re-generation / "fix this bullet" LLM round-trip (nice future, out of scope). No editing bullet text inline. No PDF export.

**Acceptance criteria.**
- Every bullet renders as a card whose color + badge match `grounding[i].supported` (green verified / red not-supported); falls back to verified-styling only when a grounding entry is truly absent.
- Verified cards display the `evidence` string; flagged cards display the `issue` string (with a sensible fallback label if null).
- A summary header shows `N bullets · X verified · Y flagged` and a verified-percentage meter, consistent with `flagged_count`.
- "Copy verified bullets" copies only `supported === true` bullets; flagged/excluded ones are omitted.
- With a deliberately fabricated CV/JD pair, at least one card renders in the red "Not supported" state with its reason visible — screenshot-ready.

**Affected files.** `frontend/src/App.jsx` (+ optional `frontend/src/components/GuardrailPanel.jsx`), `frontend/src/styles.css`.

---

### T4 — Fit score ring gauge + color-coded requirement chips (P1)

**Why.** `Fit: 62/100` as plain text reads like a debug log. A circular gauge/ring with the score and a color band, plus matched/partial/missing requirements as green/amber/red chips (each chip revealing its evidence/note on hover/expand), is instantly legible and looks like analytics tooling. Resume/AI-SE value: turning structured LLM output into a considered data visualization.

**Scope.**
- **In:** A `FitGauge` (SVG or CSS conic-gradient ring) showing `overall_score`/100 with a color that shifts by band (e.g. red <50, amber 50–74, green ≥75) and the honest `summary` beside it. Requirement chips in three color-coded groups: matched (green, shows `evidence`), partial (amber, shows `note`), missing (red). Chips wrap responsively; evidence/note shown via expand or tooltip.
- **Out:** No historical score trends (that's tracker territory, T6-adjacent). No animation library — pure CSS transitions only. No editable scoring.

**Acceptance criteria.**
- Gauge renders `overall_score` as a filled ring proportional to the value, with the numeric score centered and band color correct at boundary values (49/50/74/75).
- Matched chips are green and each exposes its `evidence`; partial chips amber exposing `note`; missing chips red.
- Empty arrays render a graceful "none" state, not an empty box or a stray comma.
- Layout stays within the results panel and reflows without horizontal scroll on mobile.

**Affected files.** `frontend/src/App.jsx` (+ optional `frontend/src/components/FitGauge.jsx`), `frontend/src/styles.css`.

---

### T5 — Cold-start "waking up the server" UX (P1)

**Why.** The free Render backend sleeps and takes ~30–60s to wake. Right now the first request looks like a raw fetch failure or a long dead hang — the worst possible impression in a live demo or when a reviewer opens the deployed link. A deliberate "Waking the analysis server… (free tier, first request can take ~40s)" state with a health-check ping and automatic retry turns a bug into a sign of thoughtful engineering. Resume/AI-SE value: real-world ops awareness (cold starts, retries, graceful degradation).

**Scope.**
- **In:** On app load (or on first Analyze), ping `GET /health`; if it doesn't respond quickly, show a friendly "waking up the server" state with an explanation and a spinner/progress hint. Wrap the analyze fetch with a bounded retry/backoff so a 502/timeout during wake retries automatically instead of erroring. Surface a warm/cold indicator (small dot) once healthy. All error copy is human ("Couldn't reach the server, retrying…"), never a raw stack/`TypeError: Failed to fetch`.
- **Out:** No keep-alive cron/pinger (would need infra; explicitly out). No SSR. No service worker.

**Acceptance criteria.**
- With the backend cold/unreachable, the UI shows the "waking up" message with the ~40s expectation, not a raw error.
- The analyze call retries at least once on transient failure/timeout before showing a final, friendly error.
- Once `/health` returns ok, the warm indicator reflects healthy state.
- No unhandled promise rejection or raw `Failed to fetch` text ever reaches the user.

**Affected files.** `frontend/src/api.js` (health ping + retry helper), `frontend/src/App.jsx` (waking/warm state UI), `frontend/src/styles.css`.

---

### T6 — Application tracker (localStorage, applied → interview → offer) (P1)

**Why.** This is the feature that most decisively separates ApplyLens from a chat paste: a persistent, per-job workspace. Users save each analysis against a job (title + company) and move it through statuses applied → interviewing → offer/rejected, with the fit score and flagged-count visible at a glance. It makes the tool something you return to across a whole search. Resume/AI-SE value: product thinking + state management, delivered with zero backend cost.

**Scope.**
- **In:** A "Save to tracker" action on a completed analysis that stores a record (job title/company, timestamp, fit score, flagged_count, and the full analysis payload) in `localStorage`. A tracker view (tab or side panel) listing saved applications grouped/filterable by status, each showing title, company, score, flagged count, and date. Status can be changed via a dropdown/segmented control (applied / interviewing / offer / rejected). Delete a record. Click a record to re-open its saved analysis (guardrail + gauge) without re-calling the LLM. All persisted in `localStorage` under a versioned key; survives refresh.
- **Out:** No cross-device sync, no database, no auth, no export/import file (could be a fast-follow). No drag-and-drop Kanban board — a status control is sufficient for this pass (Kanban is a stretch goal if time remains).

**Acceptance criteria.**
- Saving an analysis creates a `localStorage` record; it persists across a full page reload.
- The tracker lists saved apps with title, company (editable at save time), fit score, flagged count, status, and date.
- Changing an app's status updates and persists it; deleting removes it from storage.
- Re-opening a saved app renders its guardrail + fit visuals from stored data with **no** network/LLM call.
- Corrupt/missing localStorage is handled gracefully (empty tracker, no crash) via a versioned key + try/catch parse.

**Affected files.** `frontend/src/App.jsx`, new `frontend/src/tracker.js` (storage helpers), new `frontend/src/components/Tracker.jsx`, `frontend/src/styles.css`.

---

### T7 — Trust panel: surface eval / guardrail accuracy (P2, credibility)

**Why.** The eval harness proves the guardrail actually works (accuracy + fabrication precision/recall) — but that proof is invisible, buried in a script. Surfacing it in the UI ("Guardrail accuracy: 100% · fabrication recall: 100% — measured on a labeled eval set") next to the guardrail turns a claim into evidence. This is the single most "AI-SE" signal in the product: you measured your AI and you show the number. Chat has no such number.

**Scope.**
- **In:** Make `evals/run_evals.py` also emit a machine-readable `evals/results.json` (accuracy, fabrication precision, recall, dataset size, timestamp). Bundle that JSON into the frontend build (import it) and render a compact, honest "Trust & accuracy" badge/panel in the header and near the guardrail summary, with a one-line explanation and a link to the methodology (README/evals). Copy must be honest about it being a small labeled set.
- **Out:** No live/on-demand eval runs from the browser (would burn API + infra). No charts library — a couple of stat tiles is enough. Numbers are build-time static, refreshed by re-running evals; do not fabricate metrics if `results.json` is absent (show a neutral "evals available in repo" state).

**Acceptance criteria.**
- `python evals/run_evals.py` writes `evals/results.json` with `accuracy`, `precision`, `recall`, `n`, and a timestamp, in addition to its console output.
- The frontend renders these metrics as stat tiles; when `results.json` is missing/empty it shows a neutral fallback, never invented numbers.
- Copy states the eval is a small labeled dataset (honest framing), with a pointer to the harness.
- The trust panel is visible without scrolling the results (header badge) and reinforced beside the guardrail summary.

**Affected files.** `evals/run_evals.py`, new `evals/results.json` (generated), `frontend/src/App.jsx` (+ optional `frontend/src/components/TrustPanel.jsx`), `frontend/src/styles.css`, `README.md`.

---

## Suggested build order

1. **T1** (one-call flow) and **T2** (app shell) first — everything renders into them.
2. **T3** (guardrail hero) — the differentiator; the money screenshot.
3. **T4** (fit gauge/chips) and **T5** (cold-start) — polish that makes the demo feel real.
4. **T6** (tracker) — the "workflow, not a chat" feature.
5. **T7** (trust panel) — the credibility capstone.

## Risks / open questions

- **Company/title for tracker (T6):** extraction gives a job `title` but not the employer. Decide: prompt the user for company at save time (recommended, simplest) vs. add company to the extract schema.
- **Guardrail latency (T3):** tailoring already makes 2 LLM calls (generate + fact-check). The one-call `/api/analyze` (T1) adds extract+fit in parallel — verify total wall-time is acceptable on Groq; parallelization should keep it ≈ the slowest single call.
- **Eval honesty (T7):** dataset is 5 rows. Frame metrics as "on a small labeled set" — do not oversell. Consider growing `dataset.jsonl` to ~15–20 rows in the same pass if cheap.
- **No test framework on the frontend:** acceptance is manual/visual. If desired, a follow-up ticket can add a couple of Vitest component tests for the guardrail zip logic and tracker storage helpers.
