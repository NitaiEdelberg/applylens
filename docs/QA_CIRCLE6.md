# QA Circle 6 — T8: Self-correcting "Fix this bullet" loop

Date: 2026-07-12
Role: QA/Test (qa-tester)
Ticket: T8 — close the loop from detection to grounded correction (docs/NEXT_IDEA.md)

## Environment / build gates

| Gate | Result |
|------|--------|
| `frontend: npm run build` | PASS — vite built in ~1.3s, 38 modules, no errors |
| `backend: python -m pytest -q` | PASS — 4 passed in 0.62s |
| Backend boot + `/health` | PASS — `{"status":"ok"}` within 1s (see note B1 re: start.sh) |

## Live endpoint tests — POST /api/regenerate-bullet

| Case | Expected | Observed | Result |
|------|----------|----------|--------|
| Valid `{jd_text,cv_text,bullet,issue}`, fabricated "Kubernetes" bullet | 200, `{bullet, grounding{supported,evidence,issue}}`, red→green | 200; new bullet "Designed PostgreSQL schema and built REST APIs using Python and FastAPI"; grounding.supported=true, evidence set, issue=null | PASS |
| Empty/whitespace `bullet` | 400 | 400 `{"detail":"'bullet' is required"}` | PASS |
| Empty `jd_text` | 400 | 400 `{"detail":"'jd_text' is required"}` | PASS |
| Empty `cv_text` | 400 | 400 `{"detail":"'cv_text' is required"}` | PASS |
| `bullet` field absent entirely | 4xx, no unhandled 500 | 422 pydantic "Field required" | PASS (standard validation, not a 500) |
| Unsupportable claim ("published ML papers" vs cashier CV) | honest verdict, no fake green | 200; loop dropped the fabricated claim and grounded to real CV facts (supported=true, evidence="Handled cash register and customer service") | PASS |

## Acceptance criteria — backend

| Criterion | Result | Notes |
|-----------|--------|-------|
| 200 with `{bullet, grounding}` matching GroundingCheck (supported/evidence/issue) | PASS | Verified live + schema RegenerateBulletResponse (schemas.py:67) |
| Regeneration prompt receives failing `issue` | PASS | `_generate_replacement` injects `issue_line` (tailor.py:60-66) |
| Missing jd/cv/bullet → 400; LLM failure → 502 (never unhandled 500) | PASS | `_require` (server.py:90) + `_safe`→LLMError→502 (server.py:95-100) |
| Bullet **independently re-checked** via `check_grounding` — verdict NOT trusted from generation | PASS | tailor.py:109 calls `check_grounding(cv_text, [new_bullet])`; verdict read from its result, never from the generation step |
| At most one extra self-correction retry, then best attempt with honest verdict | PASS | `_MAX_ATTEMPTS = 2` loop (tailor.py:46,107); returns `best` after bound; only early-returns on `supported` (tailor.py:117); feeds fresh issue back (tailor.py:120) |
| Never fabricate a green | PASS | `best` always carries the real `check_grounding` verdict |

## Acceptance criteria — frontend (code review)

| Criterion | Result | Location |
|-----------|--------|----------|
| Fix button only on FLAGGED cards | PASS | `{!ok && canFix && (...)}` GuardrailPanel.jsx:211 |
| Fix hidden when jd/cv absent (canFix) | PASS | `canFix = !!(jdText&&jdText.trim()&&cvText&&cvText.trim())` GuardrailPanel.jsx:45 |
| On success swaps text+verdict in local state → badge/evidence/meter/counts update | PASS | `setItems` updates text/supported/evidence/issue (jsx:100-115); verifiedCount/flaggedCount/pct derive from `items` (jsx:82-84) |
| Verified fix shows "corrected"/"was flagged" marker | PASS | `↺ Corrected` + `was flagged: {prevIssue}` (jsx:201-206) |
| Newly-verified fix included by default in copy | PASS | `if (supported) setIncluded(...true)` (jsx:117-119) |
| Still-flagged stays red honestly (no fake green) | PASS | supported=false keeps badge--danger + gcard--flagged; corrected marker gated on `ok` so a still-flagged card shows no green marker; button offers "Try fixing again" |
| Per-card loading + friendly error | PASS | `fixing[i]` spinner (jsx:219); `fixError[i]` message (jsx:222); error text from api friendlyMessage |
| App passes analyzedJd/analyzedCv to GuardrailPanel | PASS | `jdText={analyzedJd} cvText={analyzedCv}` App.jsx:290; set on analyze (App.jsx:147-148) |
| onOpen (re-opened saved analysis) clears them so Fix hides | PASS | `setAnalyzedJd(''); setAnalyzedCv('')` App.jsx:185-187 |
| api.js `regenerateBullet` uses postWithRetry (cold-start retry + friendly errors) | PASS | api.js:113-114 |

## Regression checks

| Check | Result | Notes |
|-------|--------|-------|
| meter % recomputes from mutable items after fix | PASS | `pct` from `items` (jsx:84) |
| verified/flagged counts recompute from items | PASS | `verifiedCount`/`flaggedCount` from `items` (jsx:82-83) |
| copy-selected recomputes from items + included | PASS | `includedBullets = items.filter((_,i)=>included[i]).map(text)` (jsx:128) |
| items/included/fixing/fixError reset on new analysis | PASS | `useEffect([initialItems])` reseeds all (jsx:75-80) |

## Bugs / observations

- **B1 (Minor / ops, not T8):** `backend/start.sh` execs `uvicorn` directly and does not activate `.venv`, so `PORT=8000 ./start.sh` fails with `exec: uvicorn: not found` unless the venv is already active on PATH. Boot succeeded after `source .venv/bin/activate`. On Render (deps installed to the system/global env) this is a non-issue; flagged only because the literal launch command in the ticket needs the venv active locally. File: backend/start.sh:3. No T8 acceptance criterion affected.
- **B2 (Nit, by-design):** A regenerated bullet that remains flagged shows no "corrected" marker (marker is gated on `ok`, GuardrailPanel.jsx:201). This is consistent with "stay honestly red" and the button switches to "Try fixing again", so the repair attempt is still discoverable. Not a defect.

No correctness defects found in T8 scope.

VERDICT: PASS
