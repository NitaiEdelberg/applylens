# ApplyLens — Next Idea (single high-leverage ticket)

_PM pick, 2026-07-12. One idea, chosen for the best value/effort and the strongest AI Solutions Engineer story. Free-tier only: no new infra, no DB, localStorage-compatible._

---

## T8 — "Fix this bullet": close the loop from detection to grounded correction (P0, HERO+)

### Why

**User value.** Today the guardrail is a dead end for the user. When a bullet is flagged "Not supported," the only affordances are *exclude it* or *copy around it* — the user loses that content and is left to hand-fix it in a separate chat. A **Fix this bullet** action turns detection into a fix: it re-generates that single bullet, this time *conditioned on the exact reason it failed* ("claims Kubernetes, which is not in the CV"), then re-runs the grounding check on the new bullet and swaps the card in place with its fresh verdict — visibly flipping red → green (or staying flagged, honestly, if the CV genuinely can't support the claim). The user ends up with a usable, grounded bullet instead of a hole.

**AI-SE resume value.** This is the single most impressive applied-AI pattern the product could add: a **closed detection → repair → re-verification loop** — i.e. an LLM guardrail whose *output feeds back as structured input to a targeted, constraint-conditioned regeneration, which is then re-graded by the same guardrail*, with bounded retries and graceful degradation. That is the critique-and-revise / self-correction loop that senior applied-AI work is judged on, and it is far more differentiated than "we single-shot a prompt." The founder gets a genuinely new resume clause: *"designed a self-correcting guardrail loop that not only detects fabricated resume claims but repairs them under the failure reason and re-verifies the fix."*

**Why chat can't do it.** A raw ChatGPT/Claude paste has no structured verdict object to feed back, doesn't automatically re-verify its own correction against the source CV, and won't bound-and-degrade the retry. ApplyLens passes the machine-readable `issue` back into a scoped single-bullet regeneration and then independently re-checks the *new* bullet with the same fact-checker — a mechanical closed loop a chat window structurally cannot reproduce. It also shows the before → after verdict flip as proof the loop did its job.

### Scope

**In**
- **Backend service:** add `regenerate_bullet(jd_text, cv_text, bullet, issue) -> dict` in `tailor.py`. It prompts (temp ~0.4, JSON mode) for **one** replacement bullet that (a) stays tailored to the JD, (b) uses ONLY CV facts, and (c) explicitly avoids the flagged `issue`; then calls the existing `check_grounding(cv_text, [new_bullet])` and returns `{ "bullet": str, "grounding": <GroundingCheck> }`. Bounded self-correction: if the regenerated bullet is *still* unsupported, retry once more; after the bound, return the best attempt with its honest (possibly still-flagged) verdict — never fabricate a green.
- **Endpoint:** `POST /api/regenerate-bullet` taking `{jd_text, cv_text, bullet, issue}`, reusing `_require`/`_safe`/`LLMError` (→ 400 on missing input, 502 on LLM failure).
- **Schemas:** `RegenerateBulletRequest` and `RegenerateBulletResponse { bullet: str, grounding: GroundingCheck }`.
- **Client:** `regenerateBullet(jd, cv, bullet, issue)` in `api.js`, reusing `postWithRetry` (inherits cold-start retry/backoff + friendly errors).
- **UI:** on **flagged** guardrail cards only, a "Fix this bullet" button. On click: per-card spinner; on success, replace that bullet's text + verdict in local state so the card re-renders (badge, evidence/reason, meter %, and verified/flagged counts all update). Show a subtle "corrected" marker and, when it flips, a one-line "was flagged: <old issue>" so the repair is visible. Regenerated-then-verified bullets become eligible for "Copy selected bullets."
- **Inputs plumbing:** pass `jdText`/`cvText` from `App` state into `GuardrailPanel` so it can call the endpoint. When those are absent (a saved analysis re-opened from the tracker — inputs aren't persisted), hide/disable the Fix button gracefully.

**Out**
- No inline free-text editing of bullets (this is regenerate, not a text editor).
- No "fix all flagged" batch button this pass (single-bullet keeps LLM calls and UX bounded; batch is a fast-follow).
- No persisting jd/cv into tracker records (keeps localStorage small; re-opened analyses simply don't offer Fix — noted as fast-follow).
- No change to the one-shot `/api/analyze` shape; regenerate is a separate, on-demand call.
- No cover-letter regeneration.

### Acceptance criteria

- `POST /api/regenerate-bullet` with valid `{jd_text, cv_text, bullet, issue}` returns `200` with `{bullet, grounding}` where `grounding` matches the existing `GroundingCheck` shape (`supported`, `evidence`, `issue`).
- The regeneration prompt receives the failing `issue`; missing `jd_text`/`cv_text`/`bullet` returns `400`; an LLM failure surfaces as `502`, never an unhandled 500.
- The returned bullet is **independently re-checked** via `check_grounding` (not trusted from the generation step); the endpoint performs at most one extra self-correction retry, then returns the best attempt with an honest verdict.
- In the UI, "Fix this bullet" appears only on flagged cards; clicking shows a per-card loading state and, on success, swaps the card's text and verdict in place. When the fix succeeds, the card visibly flips to green with evidence and the summary counts + % meter update to match; when it can't be grounded, the card stays honestly flagged (no fake green).
- A newly-verified regenerated bullet is included by default in "Copy selected bullets."
- On a re-opened saved (tracker) analysis where inputs aren't available, the Fix button is hidden/disabled with no error.
- Cold/slow server: the regenerate call inherits `postWithRetry` behavior — retries transient failures and shows a friendly message, never a raw `Failed to fetch`.

### Affected files

- `backend/src/services/tailor.py` — new `regenerate_bullet(...)` (reuses `chat_json` + `check_grounding`).
- `backend/src/schemas.py` — `RegenerateBulletRequest`, `RegenerateBulletResponse`.
- `backend/src/server.py` — `POST /api/regenerate-bullet` (reuse `_require`/`_safe`).
- `frontend/src/api.js` — `regenerateBullet(jd, cv, bullet, issue)`.
- `frontend/src/components/GuardrailPanel.jsx` — Fix button on flagged cards; in-place bullet/verdict swap; "corrected / was-flagged" marker. Accept `jdText`/`cvText` props.
- `frontend/src/App.jsx` — pass `jd`/`cv` (or the analyzed inputs) into `GuardrailPanel`; hide Fix for re-opened saved analyses.
- `frontend/src/styles.css` — Fix button, per-card loading, corrected marker styles.
- `evals/dataset.jsonl` (optional, cheap) — a couple of rows exercising the re-check of a corrected statement.
- `README.md` — add `/api/regenerate-bullet` to the API table and mention the self-correcting loop.

### Rough effort

~0.5–1 focused day. Backend ~1–2h (one service fn + endpoint + schemas, all reusing existing primitives). Frontend ~2–4h (per-card action, in-place state swap, styling, the props plumbing + saved-analysis edge case). Manual acceptance via a deliberately fabricated CV/JD pair — no new test framework required.

### Risks / open questions

- **Latency.** Fix = 1 generate + 1 re-check, ×(up to 2 attempts) = up to 4 LLM calls, on-demand per bullet. Acceptable because it's user-initiated and single-bullet; keep the retry bound at 1 extra attempt.
- **Still-flagged regenerations.** Some claims genuinely can't be grounded in the CV. The loop must degrade honestly (stay red) — this is a *feature* of the trust story, not a bug; copy should say so.
- **Inputs for re-opened analyses.** Decision this pass: hide Fix when jd/cv aren't in state. If we later want Fix everywhere, persist `jd_text`/`cv_text` into the tracker record (small storage cost) as a fast-follow.

---

## Why this over the runners-up

- **vs. LLM-as-judge self-consistency / confidence score on verdicts.** Strong credibility-polish and a nice calibration story, but it *multiplies* grounding LLM calls (worse on free-tier latency/cost), and — critically — it doesn't change what the user can *do* with a flagged bullet. It makes the existing number fancier; it doesn't give the user a fix or add a new capability. Lower user value, higher recurring cost.
- **vs. cover-letter grounding pass.** Genuinely useful and cheap (the cover letter is currently un-checked — a real gap), but it's an *extension* of the detection story we already ship, not a new capability. It doesn't add the repair loop, which is the more impressive and more chat-proof AI-SE narrative. Good candidate for a later, low-effort ticket; not the single highest-leverage move now.
- **Why T8 wins.** It is the only option that adds a *new* AI capability (self-correction), is directly and obviously useful to the user (a fix, not a hole), is mechanically impossible for a chat paste to replicate (structured reason fed back + independent re-verification + bounded degradation), and reuses every existing primitive (`chat_json`, `check_grounding`, `postWithRetry`, the guardrail card UI) so effort stays low. Best value/effort and best resume clause in one ticket.
