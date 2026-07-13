# ApplyLens 🔎

An AI copilot for the job hunt. Paste a job description and your CV, and ApplyLens:

1. **Extracts** the posting into structured requirements (must-haves, nice-to-haves, stack)
2. **Scores your fit** against the role — strictly evidence-based (matched / partial / missing)
3. **Tailors** resume bullets + a cover letter, **grounded** in your real CV
4. **Guards against fabrication** — a grounding check flags any generated claim your CV doesn't support
5. **Grounds the cover letter too** — it extracts only the letter's factual claims about your background and checks those against your CV (boilerplate like greetings and "I'm excited to apply" is never flagged)
6. **Adds a deterministic ML second opinion** — a CPU-only scikit-learn keyword-coverage signal checks which of the job's requirement terms actually appear in the CV (covered vs. missing), independent of (and complementing) the LLM's semantic fit score
7. **Tailors from your whole career (optional RAG)** — paste a longer career history (extra roles, projects, a brag doc) and, per job, a **LangChain** retrieval chain surfaces the most relevant real experiences; tailoring draws on that fuller background while the guardrail grounds against **CV + retrieved chunks** (so a bullet backed by a real retrieved experience is legitimately verified, and anything in neither is still flagged)

![ApplyLens — the grounding guardrail verifying each tailored bullet against the CV, with a measured-accuracy trust badge](docs/screenshot.png)

It's a **workspace, not a chat box** — three things a raw ChatGPT/Claude paste structurally can't give you:
- **Trust you can see** — every tailored bullet is labeled *"verified against your CV"* (with the evidence) or *"not supported"* (with the reason). Chat will happily invent "Led a team of 8 at Google"; ApplyLens flags it.
- **A workflow across many jobs** — analyses are saved to a tracker and moved applied → interviewing → offer. Chat loses everything on refresh.
- **Measured accuracy** — the guardrail is graded by an eval harness: **100% accuracy / 100% fabrication recall on a labeled set (n=33)**, surfaced in the UI. Chat gives you vibes; this gives you a number.

Built as a real tool *and* a showcase of applied-AI engineering: structured LLM extraction, LLM-as-judge scoring, grounded generation, a user-facing anti-hallucination **guardrail**, an **eval harness** with precision/recall, and a polished dark SaaS UI with cold-start-aware UX.

## Architecture

```
React (Vite)  ──►  FastAPI  ──►  Groq (OpenAI-compatible LLM)
                     │
   /api/extract  ──  extract.py     JD text     → structured requirements
   /api/fit      ──  fit.py         JD + CV     → evidence-based fit score
   /api/tailor   ──  tailor.py      JD + CV     → tailored bullets + cover letter
                        └── grounding.py  each bullet → supported? (guardrail)
   /api/analyze  ──  rag.py (opt)   career_text → top-k relevant chunks (LangChain)
                        └── tailor + grounding source = CV + retrieved chunks
evals/run_evals.py     grounding guardrail → accuracy + fabrication precision/recall
```

## Tech stack

**Backend:** Python · FastAPI · httpx · Groq (`llama-3.3-70b-versatile`) · scikit-learn (deterministic keyword-coverage skill-match + RAG TF-IDF fallback embedder) · LangChain (`langchain-core` retrieval chain for the optional RAG career corpus) · SQLAlchemy (accounts + cloud tracker; SQLite locally, Postgres in prod) · passlib/bcrypt + PyJWT (auth)
**Frontend:** React + Vite
**Evals:** labeled JSONL dataset + a runnable scorer

## Run it

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your free Groq key: https://console.groq.com/keys
./start.sh                    # http://localhost:8000  (docs at /docs)
```

**Frontend**
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api to :8000)
```

**Tests & evals**
```bash
cd backend && pytest                       # smoke + auth/tracker tests (no key/DB needed)
GROQ_API_KEY=... python evals/run_evals.py # grounding guardrail metrics
```

### Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | LLM key (required for analyze/tailor; tests don't need it) |
| `DATABASE_URL` | `sqlite:///./applylens.db` | Accounts + cloud tracker DB. Unset = local SQLite (no credential). In prod set to the **Supabase session-pooler URI**. `postgres://` is auto-normalized to `postgresql://`. |
| `JWT_SECRET` | dev fallback | Signs auth tokens. Set a long random value in production. |
| `GEMINI_API_KEY` | — | **Optional** RAG embeddings key. Unset = deterministic local TF-IDF embedder (no network — RAG fully works with no credential). Set to activate hosted Gemini `text-embedding-004` (1,500 req/day free). |
| `GEMINI_EMBED_MODEL` | `text-embedding-004` | Gemini embeddings model used when `GEMINI_API_KEY` is set. |

### Keeping the free-tier DB awake

Supabase pauses a free project after ~7 days idle. `.github/workflows/keepalive.yml`
is a scheduled GitHub Action that pings `GET /api/keepalive` every 3 days.
**The repo owner must enable GitHub Actions** for it to run (and optionally set a
`BACKEND_URL` repo variable to override the default deployed URL).

## API

| Endpoint | Body | Returns |
|---|---|---|
| `GET /health` | — | `{"status":"ok"}` |
| `POST /api/extract` | `{jd_text}` | structured requirements |
| `POST /api/fit` | `{jd_text, cv_text}` | `overall_score`, matched/partial/missing, summary |
| `POST /api/tailor` | `{jd_text, cv_text}` | `bullets`, `cover_letter`, `grounding[]`, `flagged_count`, `cover_grounding[]`, `cover_flagged_count` |
| `POST /api/analyze` | `{jd_text, cv_text, career_text?}` | `{job, fit, tailor, skill_match, rag}` — runs extraction/fit/tailoring concurrently, then adds a deterministic (non-LLM) keyword-coverage `skill_match` signal. When optional `career_text` is present, RAG retrieves the top-k relevant career chunks and tailoring grounds against CV + chunks; `rag` = `{used, chunks[], source}` (`used:false` when omitted) |
| `POST /api/regenerate-bullet` | `{jd_text, cv_text, bullet, issue}` | `{bullet, grounding}` — self-correcting loop: regenerate one flagged bullet conditioned on its failure reason, then independently re-verify it |
| `POST /api/auth/register` | `{email, password}` | `{token, email}` — creates an account (bcrypt-hashed password) and returns a JWT |
| `POST /api/auth/login` | `{email, password}` | `{token, email}` — returns a JWT |
| `GET /api/tracker` | — _(Bearer token)_ | this user's saved applications, newest first |
| `POST /api/tracker` | `{title, company?, status?, score?, flagged?, payload?}` _(Bearer)_ | creates a tracked application for the current user |
| `PATCH /api/tracker/{id}` | `{status}` _(Bearer)_ | updates status; 404 if not yours |
| `DELETE /api/tracker/{id}` | — _(Bearer)_ | deletes; 404 if not yours |
| `GET /api/keepalive` | — | `{ok:true}` — trivial `SELECT 1`; pinged by a cron to keep a free-tier DB awake |

### Optional accounts + cloud tracker

Accounts are **optional**. Anonymous users keep the browser-local `localStorage`
tracker exactly as before; signing in swaps the tracker's data source to a
per-user, JWT-protected API so applications sync across devices (and a one-time
offer imports existing local applications on first login). Persistence uses
**SQLAlchemy**, so it runs on **SQLite locally with no credential** and
**Postgres in production** (e.g. Supabase). Tracker rows are strictly
user-scoped — a user can only ever see or modify their own.

### Self-correcting guardrail loop

`/api/regenerate-bullet` closes the loop from **detection → repair → re-verification**.
When the guardrail flags a bullet as fabricated, its machine-readable `issue`
is fed back into a scoped, constraint-conditioned regeneration of that single
bullet, and the **new** bullet is then re-graded by the same fact-checker
(`check_grounding`) — never trusting the generation step. It self-corrects with
one bounded retry, then degrades honestly: if the CV genuinely can't support the
claim, the card stays flagged instead of fabricating a green.

### Optional RAG career corpus (LangChain)

Tailor from your **whole** career, not one pasted CV. Paste a longer career
history (extra roles, projects, a brag doc) into the optional *"Career history"*
field and, per job, ApplyLens retrieves the most relevant real experiences and
tailors from them — while the guardrail stays honest.

- **Pipeline** (`backend/src/services/rag.py`): chunk the career text by
  paragraph (dropping tiny fragments) → embed → store in a `langchain-core`
  `InMemoryVectorStore` → `as_retriever(search_kwargs={"k": 4})` retrieves the
  top-k chunks most relevant to the job's extracted requirements.
- **Pluggable embedder** (both implement LangChain's `Embeddings` interface):
  - `GeminiEmbeddings` — hosted Gemini `text-embedding-004` via httpx, used when
    `GEMINI_API_KEY` is set. Invalid key / network failure **falls back cleanly**
    to TF-IDF.
  - `TfidfEmbeddings` — a local scikit-learn TF-IDF embedder fit on the corpus
    chunks (queries project into the same space). Deterministic, no network — so
    **the whole feature is testable and usable with no credential.**
- **Grounding stays honest:** when RAG is used, the tailor + `check_grounding`
  source of truth becomes `cv_text + "\n".join(retrieved chunks)`. A bullet
  supported by a real retrieved experience is legitimately verified; anything in
  neither the CV nor the retrieved chunks is still flagged. Only `langchain-core`
  (pure-Python) is added — no heavy LangChain packages, deploy-safe on the free tier.

Response adds `rag: {used, chunks[], source}`. Omit `career_text` and behavior is
identical to before (`rag.used = false`).

## Roadmap

- "Fix all flagged bullets" batch action (single-bullet fix ships today)
- Export the tailored resume + cover letter (PDF / Markdown)
- Persist the RAG career corpus per-user in Supabase pgvector (embed-on-ingest)
- Server-side persistence (Postgres) + a per-provider LLM fallback

## Development team (subagents)

This repo defines a small agent team under `.claude/agents/` — `product-manager`,
`developer`, `qa-tester`, and `bug-fixer` — used to plan, build, test, and fix
features. See each file for its role and scope.
