# ApplyLens — Release Notes: "Workspace, not a chat box"

_PM sign-off · 2026-07-12 · Covers the T1–T7 improvement effort delivered across 5 build circles. QA: PASS (see `QA_FINAL.md`)._

## Why this release

Founder critique going in: _"it doesn't look cool enough — it looks like something I could do by pasting my resume + a job description into Claude."_ The goal was to make ApplyLens (1) visibly a **product**, not a chat wrapper; (2) a credible **AI Solutions Engineer** resume piece; (3) a polished modern SaaS web app. This release answers all three.

## What shipped (T1–T7)

| Ticket | What shipped |
| --- | --- |
| **T1** | One-call `POST /api/analyze` — runs extract + fit + tailor concurrently (`asyncio.gather`), returns one `{job, fit, tailor}` payload. One action, one coherent result; errors surface as clean 4xx/502, never a 500. |
| **T2** | Dark SaaS design system — CSS token layer (palette/spacing/radius), sticky header with gradient wordmark + tagline, responsive two-pane → single-column shell, styled textareas / primary button / loading + empty states. Zero hex in JSX. |
| **T3** | **Guardrail hero** — every tailored bullet is a color-coded card: green "Verified against your CV" + evidence, or red "Not supported" + the reason. Summary bar (`N bullets · X verified · Y flagged`), % verified meter, per-bullet include/exclude, "Copy selected bullets," collapsible cover letter. This is the screenshot that sells the product. |
| **T4** | **FitGauge** — SVG ring gauge with band colors (red <50 / amber 50–74 / green ≥75), centered score, and matched/partial/missing requirement chips that expand to show evidence/notes. Structured LLM output rendered as analytics, not a debug line. |
| **T5** | **Cold-start UX** — `/health` ping on load drives a warm/cold dot; analyze retries with bounded backoff; a friendly "Waking up the analysis server… ~40s" state replaces raw `Failed to fetch`. Real ops awareness for a free-tier deploy. |
| **T6** | **Application tracker** — save each analysis (title, company, score, flagged count, full payload) to versioned localStorage; move it applied → interviewing → offer/rejected; re-open a saved analysis with **no** LLM call; corrupt storage degrades to empty, never crashes. The feature a chat paste structurally cannot have. |
| **T7** | **Trust panel** — `run_evals.py` emits `results.json`; the UI shows measured guardrail **accuracy / fabrication recall / precision** as stat tiles plus an always-visible header badge, honestly framed as "a small labeled set (n=17)." No invented numbers when metrics are absent. |

## Positioning

**ApplyLens is a job-hunt workspace, not a chat box.** Three things a raw ChatGPT/Claude paste structurally cannot do, and this release makes each one visible in the UI:

1. **Trust you can see** — a fabrication guardrail fact-checks every generated bullet against the real CV and labels it inline with the evidence or the reason.
2. **A workflow across many jobs** — analyses persist to a tracker and move through a hiring pipeline; nothing is lost on refresh.
3. **Measured accuracy** — the guardrail is graded by an eval harness and the number is shown in the product. Chat gives you vibes; ApplyLens gives you a number.

## Verdict

**Shippable.** All automated gates pass (frontend build, backend pytest, live `/health` + `/api/analyze`); no functional bugs, broken imports, or cross-analysis state leaks. The three critique goals are met (product feel, resume story, polished SaaS UI). Residual items are non-blocking polish.

## Highest-leverage next steps

1. **Add a real screenshot / GIF of the guardrail hero to the README** — the strongest single upgrade to the resume story; right now the differentiator is described but not shown.
2. **Deploy the refreshed build** (Netlify + Render) and put the live link in the README — a reviewer clicking a working demo beats any prose; the cold-start UX (T5) exists precisely for this moment.
3. **Grow the eval set** beyond n=17 toward ~30–50 labeled statements so the surfaced accuracy carries more weight (and drop 100%/100% into a slightly more realistic, still-honest range).
4. Minor: README roadmap still lists the tracker as future work — mark it shipped.

## Resume bullet (for the founder)

> **Built ApplyLens, an AI job-hunt copilot (React + FastAPI + Groq LLM) with a user-facing anti-fabrication guardrail that fact-checks every AI-generated resume bullet against the source CV — validated by a labeled eval harness (precision/recall) whose measured accuracy is surfaced in the product, plus a persistent application-tracking workflow — turning a raw LLM paste into a trustworthy, measurable SaaS product.**
