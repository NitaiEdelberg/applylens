# QA — Circle 7 / Ticket T9: Cover-letter grounding (fact-check extracted claims only)

Date: 2026-07-12
Role: QA/Test (verify only — no product changes)
Groq: llama-3.3-70b-versatile (live key in backend/.env)

## Scope
T9 adds a cover-letter guardrail that extracts ONLY the candidate's concrete
factual self-claims from a generated cover letter and fact-checks those against
the CV — never the boilerplate prose (greetings, enthusiasm, company statements).

## Results

| # | Check | Result |
|---|-------|--------|
| 1 | `frontend` `npm run build` | PASS — built in 1.33s, 38 modules, no errors |
| 1 | `backend` `python -m pytest -q` | PASS — 4 passed in 0.58s |
| 2 | `extract_claims` prompt excludes greetings/enthusiasm/aspiration/opinions/filler/company+role | PASS — both system + user prompt enumerate all exclusions |
| 2 | `extract_claims` returns `[]` on empty/whitespace/no-claims | PASS — early `return []` guard + `{"claims": []}` contract |
| 2 | `extract_claims` filters non-string/empty entries | PASS — `[c.strip() for c in claims if isinstance(c, str) and c.strip()]` |
| 2 | `check_cover_letter` chains extract_claims -> check_grounding | PASS |
| 2 | `check_cover_letter` returns `{claims, flagged_count}` | PASS |
| 2 | Empty-claims short-circuits to `{claims:[], flagged_count:0}` (no wasted grounding call) | PASS — returns before calling `check_grounding` |
| 2 | tailor.py runs bullet grounding AND cover check CONCURRENTLY in a single `asyncio.gather` | PASS — one `asyncio.gather(check_grounding(...), check_cover_letter(...))` |
| 2 | tailor result carries `cover_grounding` + `cover_flagged_count` | PASS |
| 2 | schemas: `TailorResult.cover_grounding: List[GroundingCheck]` + `cover_flagged_count: int` | PASS |
| 2 | Fields flow through `AnalyzeResponse` (tailor: TailorResult) | PASS |
| 3 | Live MIX letter: boilerplate NOT in claims | PASS — "excited"/"resonates"/"opportunity to contribute" not extracted |
| 3 | Live MIX letter: fabrication ("led a team of 8 at Google") flagged | PASS — flagged, issue="Employer and leadership role not mentioned in CV" |
| 3 | Live all-supported letter: `flagged_count == 0` | PASS — 5 claims extracted, 0 flagged |
| 3 | Live pure-boilerplate letter: `claims=[]`, `flagged_count=0` | PASS |
| 3 | Live empty letter: `claims=[]`, `flagged_count=0` | PASS |
| 3 | `POST /api/analyze` 200 includes `tailor.cover_grounding` + `tailor.cover_flagged_count` | PASS — both keys present (len 5, cover_flagged_count 1) |
| 4 | GuardrailPanel CoverVerdict: verified/flagged/neutral verdict correct | PASS — total==0 neutral, flagged==0 ok, else flag |
| 4 | Lists flagged claims with reason when expanded | PASS — `open && flagged.length>0` renders claim + `c.issue` |
| 4 | Empty-claims renders neutral, no implied problem | PASS — "No verifiable claims", `cl__verdict--neutral` (text-dim) |
| 4 | Never flags the prose itself | PASS — only iterates extracted `grounding` claims, `<pre>` prose shown raw |
| 4 | Reuses design tokens | PASS — `--success/--danger/--text-dim/--border/--radius-sm/--sp-*`, `badge--danger`, `gcard__detail` all pre-existing |
| 4 | Build clean | PASS (see #1) |

## Live evidence (Groq)
- MIX letter -> claims = ["led a team of 8 at Google" (flagged), "built distributed
  systems at Google" (flagged), "built Python microservices at Acme Corp" (supported),
  "cut API latency by 30% with Redis at Acme Corp" (supported)]; flagged_count=2.
  Boilerplate greeting/enthusiasm/company lines were NOT extracted.
- All-supported letter -> 5 claims, flagged_count=0.
- Pure-boilerplate letter -> claims=[], flagged_count=0.
- Empty letter -> claims=[], flagged_count=0.
- POST /api/analyze -> 200, tailor.cover_grounding (len 5) + tailor.cover_flagged_count present.

## Bugs
None found. (Severity: n/a)

## Notes (non-blocking, not defects)
- On the `/api/analyze` smoke run the model's tailored bullets produced
  flagged_count=4 for the bullet guardrail; that is the existing bullet-grounding
  path (T3) doing its job on model output, unrelated to T9.
- `check_cover_letter` reuses `check_grounding`, inheriting its length-tolerant
  normalization — good defensive reuse.

VERDICT: PASS
