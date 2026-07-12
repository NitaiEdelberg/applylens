# QA — Circle 3: Accounts + Per-User Cloud Tracker (+ Privacy Footer)

**Date:** 2026-07-12
**Scope:** Optional user accounts, per-user cloud tracker (SQLite local / Postgres prod), privacy footer, keep-alive workflow.
**Mode:** Report-only. This is security-sensitive; auth + data-isolation were reviewed and exercised end-to-end.

## Environment
- Backend: `python -m pytest -q` → **20 passed** (3.67s).
- Frontend: `npm run build` → **success** (vite build, 41 modules, no errors).
- Live: backend booted on port 8099 with a throwaway SQLite DB (`DATABASE_URL=sqlite:///…`, `JWT_SECRET` set), full flow exercised via curl, server killed after. No external DB used.

## PASS / FAIL table

| # | Check | Method | Result |
|---|-------|--------|--------|
| 1 | Backend unit/integration tests | `pytest -q` | **PASS** (20 passed) |
| 2 | Frontend production build | `npm run build` | **PASS** |
| 3 | No-token `GET /api/tracker` → 401 | live curl | **PASS** (401) |
| 4 | Register → token | live curl | **PASS** (token + email, no password echoed) |
| 5 | Login → token | live curl | **PASS** (200) |
| 6 | Login wrong password → 401 | live curl | **PASS** (401, generic "Invalid email or password") |
| 7 | Duplicate register → 409 (not 500) | live curl | **PASS** (409) |
| 8 | Create / list / patch / delete tracked app | live curl | **PASS** (all 200, JSON payload round-trips) |
| 9 | Second user on user A's app id → **404** (not 403/200) | live curl | **PASS** (list empty, PATCH 404, DELETE 404) |
| 10 | Invalid token → 401 | live curl | **PASS** |
| 11 | Forged token (wrong secret) → 401 | live curl | **PASS** |
| 12 | Expired token → 401 | live curl | **PASS** |
| 13 | Token for non-existent user id → 401 (not 500) | live curl | **PASS** |
| 14 | `GET /api/keepalive` → `{ok:true}`, 200, never 500 | live curl | **PASS** |
| 15 | Passwords bcrypt-hashed, never plaintext | inspected SQLite `users` table | **PASS** (`$2b$12$…`, 60 chars) |
| 16 | Password never returned in any response | `security.py`, `schemas.py`, live responses | **PASS** (`TokenResponse` = token+email only) |
| 17 | JWT signed with `JWT_SECRET`, dev fallback | `security.py:16` | **PASS** |
| 18 | Token payload doesn't trust client-supplied user id | `security.py:36`, `server.py:162` | **PASS** (`sub` set server-side from `user.id`; user re-fetched from DB) |
| 19 | Tracker scoped by `current_user.id` on every read/update/delete (no IDOR) | `server.py:229-293` | **PASS** (`_owned_app` → 404 when `row.user_id != user.id`; list filters `user_id`) |
| 20 | SQLAlchemy ORM parametrized; no raw string SQL injection | `db_sql.py`, `server.py` | **PASS** (only raw SQL is literal `SELECT 1`) |
| 21 | `DATABASE_URL` defaults to SQLite when unset | `db_sql.py:28-38` | **PASS** |
| 22 | `postgres://` normalized to `postgresql://` | `db_sql.py:36-37` | **PASS** |
| 23 | No secret logged | inspected uvicorn log | **PASS** (no secret/hash/traceback) |
| 24 | Errors don't leak stack traces / internals | live curl (422 validation, malformed JSON) | **PASS** |
| 25 | Anonymous localStorage tracker still works when logged out | `App.jsx:188-208`, `tracker.js` | **PASS** (data source switches on `token`; anonymous path unchanged) |
| 26 | Privacy footer claims accurate vs. implementation | `Footer.jsx`, `PRIVACY.md` vs. code | **PASS** (see Privacy section) |
| 27 | Keep-alive workflow valid + hits `/api/keepalive` | `.github/workflows/keepalive.yml` | **PASS** (cron `0 6 */3 * *`, curl `-fsS`, graceful non-fatal exit) |

## Security review (detail)

- **Password hashing.** `passlib` bcrypt (`security.py:20`), 72-byte truncation guarded on both hash and verify. Stored hashes verified in DB as `$2b$12$…`. `verify_password` swallows malformed-hash exceptions → never 500s a login. No endpoint or schema returns a password or hash.
- **JWT.** HS256 signed with `JWT_SECRET` (env, dev fallback `dev-insecure-secret-change-me`, documented as MUST-override in prod). `sub` is the server-side `user.id`; `current_user` decodes, then re-fetches the user from the DB — a client cannot inject an arbitrary id. Missing / malformed / forged (wrong secret) / expired / ghost-user tokens all resolve to 401. Confirmed live.
- **Data isolation (IDOR).** List query filters `TrackedApplication.user_id == user.id`. `_owned_app` (`server.py:262`) returns **404** — not 403 — when the row is missing or not owned, so a second user cannot even confirm another user's row exists. PATCH and DELETE both route through `_owned_app`. Confirmed live: user B gets 404 on user A's app id for both PATCH and DELETE, and an empty list.
- **SQL injection.** All queries use ORM `select()` / `db.get()` with bound parameters. The only raw SQL is a literal `text("SELECT 1")` in `/api/keepalive` (no interpolation). Path param `app_id` is typed `int`, so a non-integer id 422s before touching the DB.
- **DATABASE_URL.** Defaults to `sqlite:///./applylens.db` when unset; `postgres://` → `postgresql://`; `check_same_thread` disabled for SQLite only. No secret is logged (log inspected).
- **Error hygiene.** Duplicate email → 409; short/invalid credentials → 400; malformed JSON → 422 with no stack trace; LLM errors wrapped as 502. No tracebacks or secrets in server output.

**No security defects found.** Items below are low/informational hardening notes, not blockers.

## Privacy claims vs. implementation (`Footer.jsx` + `PRIVACY.md`)

| Claim | Accurate? | Evidence |
|-------|-----------|----------|
| Anonymous data stays in localStorage, never on our servers | **TRUE** | `tracker.js` uses `localStorage`; anonymous path in `App.jsx` never calls the API; analyze endpoints don't persist input. |
| Submitted text goes to Groq | **TRUE** | `config.py` `GROQ_URL`; `llm.py` posts to Groq. Backend does not persist analyze text. |
| Accounts store email + saved applications (title, company, status, saved analysis) + hashed password | **TRUE** | `db_sql.py` `User`(email, password_hash) + `TrackedApplication`(title, company, status, score, flagged, payload). |
| You can delete any saved application; can request account deletion | **TRUE (with note)** | `DELETE /api/tracker/{id}` works. Account deletion is worded as "request" (manual) — there is no self-serve account-deletion endpoint, so the wording is honest. See B3. |
| No selling/ads/third-party trackers | **TRUE** | No analytics scripts or external hosts in `frontend/index.html` or `src` (only the app's own module). |

## Bugs / observations (all low / informational — no fixes required for sign-off)

- **B1 (Low, informational) — `server.py:51` CORS `allow_origins=["*"]`.** Wide-open CORS with `allow_headers=["*"]`. Acceptable here because auth is Bearer-token (not cookies), so there's no credentialed cross-origin risk, and the code already comments "tighten for production." Recommend restricting to the Netlify origin in prod.
- **B2 (Low, informational) — `security.py:16` dev JWT fallback.** `JWT_SECRET` falls back to a known constant when unset. This is explicitly allowed for dev/tests and documented in `.env.example`, but production **must** set `JWT_SECRET` or anyone could mint valid tokens. Deployment-config concern, not a code defect.
- **B3 (Low) — no self-serve account-deletion endpoint** (`server.py`). Privacy text promises users can "request account deletion." The claim is honest (it says *request*, implying a manual/email process), but there is no `/api/auth/delete` endpoint. Fine for a portfolio project; note it so the promise stays deliverable. `User → applications` uses `cascade="all, delete-orphan"`, so a manual user delete would clean up rows correctly.
- **B4 (Low) — `TrackerStatusUpdate.status` unvalidated** (`schemas.py:120`, `server.py:278`). Any arbitrary string is accepted as a status (the frontend's `STATUSES` enum isn't enforced server-side). Data-hygiene only, not a security issue; consider validating against the allowed set.

## VERDICT: PASS
