# ApplyLens — Explained Simply (build story + every concept)

A plain-language guide to what ApplyLens is, **how it was planned and built**, and **every programming/tech concept in it** — for each one: *what it is, what it does, how it's implemented in this code, and why.* Use this to study the project and to explain it to others.

---

## 1. What ApplyLens is (in one breath)

You paste a **job description** and your **CV** (or upload a PDF/DOCX). ApplyLens reads the job, scores how well you fit, and rewrites your experience into tailored résumé bullets + a cover letter — and a **guardrail** fact-checks every generated line against your real CV so it never invents things. You can save each job to a **tracker**, search it, and (optionally) sign in to sync across devices.

**The one-line pitch:** it's a job-hunt *workspace* with a trust layer, not a chat box — it gives you verified, measurable, trackable output a raw ChatGPT/Claude paste can't.

---

## 2. How it was planned & built (the process)

This wasn't built in one shot. It was built like a small software company, in **iterations ("circles")**, each a mini-project:

1. **Plan (Product Manager):** write a short "ticket" for a feature — *why* it matters, *what's in/out of scope*, and *acceptance criteria* (a checklist of "done").
2. **Build (Developer):** implement the smallest correct version.
3. **Test (QA):** verify it against the acceptance criteria, live.
4. **Fix (Bug-fixer):** fix what QA found.
5. **Sign off (PM/CTO/Sales):** confirm it's shippable and adds real value.

Every circle ended with the code **committed to Git**, **pushed to GitHub**, and **auto-deployed** live. Roles were played by focused AI sub-agents (defined in `.claude/agents/`), with a human CEO (you) making the product calls and providing accounts/keys.

**Why this way:** small, verified steps mean the app is always working and every change is reviewed — the same reason real teams use sprints, code review, and CI/CD.

---

## 3. The shape of the system (architecture)

```
   Your browser (Frontend: React)
        │  HTTP requests (fetch)
        ▼
   Backend API (Python + FastAPI)  ──►  Groq (the LLM) — writes/judges text
        │                          ──►  Gemini or TF-IDF — embeddings for RAG
        ├──►  Postgres/Supabase (accounts + saved applications)
        └──►  Elasticsearch/Bonsai (search) — with a database fallback
```

- **Frontend** = what you see and click (runs in your browser).
- **Backend** = the "brain" on a server that does the real work and talks to the AI and databases.
- They talk over **HTTP** using **JSON** messages.

---

## 4. Every concept, explained

Format for each: **What it is → What it does here → Where in the code → Why.**

### A. Web fundamentals

**Frontend vs Backend (client/server).**
*What:* the frontend is the part in your browser; the backend is a program on a server. *Here:* the React app (in `frontend/`) is the frontend; the FastAPI app (in `backend/`) is the backend. *Why:* the browser can't safely hold secret keys or run heavy AI calls, so the backend does that and the frontend just shows results.

**HTTP + REST API + endpoints.**
*What:* HTTP is the language browsers and servers speak; a REST API is a set of named "doors" (endpoints) on the server you can knock on with a method (GET = read, POST = create/do). *Here:* endpoints like `POST /api/analyze`, `POST /api/tracker`, `GET /api/tracker/search`. *Where:* `backend/src/server.py`. *Why:* it's the standard, simple way for the frontend to ask the backend to do things.

**JSON.**
*What:* a text format for structured data (`{"key": "value"}`). *Here:* every request/response body is JSON. *Why:* both Python and JavaScript read/write it natively, so it's the lingua franca between frontend and backend.

**Status codes.**
*What:* numbers the server returns: 200 = OK, 400 = you sent something wrong, 401 = not logged in, 404 = not found, 500 = server error, 502 = upstream (AI) failed. *Here:* the API returns clean 400/401/404/502 instead of crashing. *Why:* the frontend can react correctly (show a friendly message vs. a login prompt).

### B. Frontend

**React.**
*What:* a JavaScript library for building UIs out of reusable **components** (small functions that return a piece of screen). *Here:* `App.jsx` plus components like `GuardrailPanel.jsx`, `FitGauge.jsx`, `Tracker.jsx`. *Why:* it lets the UI automatically re-draw when data changes, without manual DOM juggling.

**State + hooks (`useState`, `useEffect`).**
*What:* "state" is data that can change (what you typed, the results); "hooks" are React functions to use it. `useState` holds a value; `useEffect` runs code when something changes (e.g. on load). *Here:* `const [cv, setCv] = useState('')` holds the CV text; a `useEffect` pings the server's health on load. *Why:* when state changes, React redraws just the parts that depend on it.

**Vite.**
*What:* a build tool/dev server for frontend code. *Here:* `npm run dev` for local, `npm run build` bundles the app into static files. *Why:* fast local development and an optimized production bundle.

**SPA (single-page app).**
*What:* the whole app is one HTML page; JavaScript swaps the content instead of loading new pages. *Here:* the Analyze/Tracker "tabs" just re-render. *Why:* feels instant, like a desktop app.

**Design tokens / CSS variables.**
*What:* named values for colors, spacing, radius defined once and reused. *Here:* `:root { --bg; --accent; --success; ... }` in `styles.css`. *Why:* one consistent look; change a token, the whole app updates.

**`fetch` (calling the backend).**
*What:* the browser function to make HTTP requests. *Here:* `frontend/src/api.js` wraps `fetch` for every backend call, with retries and friendly errors. *Why:* one tidy place for all server communication.

**localStorage.**
*What:* a small storage box in your browser that survives refreshes. *Here:* the **anonymous tracker** and your login token live here (`tracker.js`). *Why:* lets anonymous users keep data with zero server/database cost.

### C. Backend

**Python + FastAPI + Uvicorn.**
*What:* Python is the language; FastAPI is a framework for building APIs quickly; Uvicorn is the server program that runs it. *Here:* `backend/src/server.py` defines endpoints; `start.sh` launches Uvicorn. *Why:* FastAPI is fast to write, self-documents (`/docs`), and validates input automatically.

**Pydantic (schemas / validation).**
*What:* Python classes that describe the exact shape of requests/responses and check them. *Here:* `backend/src/schemas.py` (`AnalyzeRequest`, `TailorResult`, etc.). *Why:* bad input is rejected with a clear error before your code runs — fewer bugs.

**Async + concurrency (`asyncio.gather`).**
*What:* "async" lets the server do other work while waiting; `gather` runs several waits **at the same time**. *Here:* `/api/analyze` runs extraction, fit-scoring, and tailoring **concurrently** instead of one-after-another. *Why:* three ~2-second AI calls finish in ~2 seconds total, not ~6.

**CORS.**
*What:* a browser security rule about which sites may call your API. *Here:* the backend allows the Netlify frontend to call it. *Why:* without it, the browser would block the frontend's requests.

**Graceful degradation / fallbacks.**
*What:* if an optional part fails, the app keeps working with a simpler version instead of crashing. *Here:* no database → accounts disabled but anonymous mode works; no Elasticsearch → database search; no Gemini key → local TF-IDF embeddings; the DB going down never crashes boot. *Why:* resilience — one broken dependency shouldn't take down the whole product.

### D. The AI core

**LLM (Large Language Model) + Groq.**
*What:* an AI trained to predict/produce text (write, summarize, judge). Groq is a provider that runs open models very fast. *Here:* `backend/src/llm.py` calls Groq's API (model `llama-3.3-70b-versatile`). *Why:* it's the engine that writes bullets, scores fit, and fact-checks — free and fast.

**Prompt engineering + structured (JSON) output.**
*What:* a "prompt" is the instruction you give the model; asking it to reply in JSON makes the answer machine-readable. *Here:* every service (`extract.py`, `fit.py`, `tailor.py`, `grounding.py`) sends a carefully-worded prompt and requests JSON. *Why:* structured output means the rest of the code can use the answer reliably (not parse free text).

**LLM-as-judge.**
*What:* using an LLM to *evaluate* something rather than generate prose. *Here:* fit-scoring judges CV-vs-job; the guardrail judges "is this bullet supported by the CV?". *Why:* some tasks are judgments, and the model is good at them when the question is precise.

**The grounding guardrail (anti-hallucination).**
*What:* a safety check that verifies each generated line against a source of truth. *Here:* `grounding.py` takes each tailored bullet and asks the model "is this supported by the CV? give evidence or the reason it isn't." Verified bullets show green + evidence; unsupported ones show red + reason. *Why:* this is the product's core trust feature — it stops the AI from inventing "Led a team of 8 at Google."

**Self-correction loop.**
*What:* detect a problem → fix it → check again. *Here:* "Fix this bullet" (`regenerate_bullet` in `tailor.py`) re-writes a flagged bullet *using the failure reason*, then **re-runs the guardrail** on the new version — flipping red→green, or honestly staying red if the CV can't support it. *Why:* it turns detection into a usable fix, and it's the impressive "self-correcting AI" pattern.

**The tailoring balance (a real lesson in this project).**
*What:* tailoring must reframe your CV toward the job *without inventing*. *Here:* the tailor prompt (`tailor.py`) was tuned so bullets are reworded/reordered for the job but stay verifiable — early versions either copied the CV verbatim (grounded but not tailored) or over-embellished (tailored but flagged). *Why:* it shows the guardrail doing real work — mostly-green bullets with the occasional caught embellishment you can fix.

**Evals (accuracy / precision / recall).**
*What:* measuring how good the AI is on a labeled test set. **Accuracy** = % it got right; **precision** = of the things it flagged as fabricated, how many really were; **recall** = of all real fabrications, how many it caught. *Here:* `evals/dataset.jsonl` (33 labeled statements) + `evals/run_evals.py` produce these numbers, shown in the app's trust panel. *Why:* "I measured my AI and show the number" is the difference between a demo and engineering.

### E. RAG & embeddings (the "career history" feature)

**RAG (Retrieval-Augmented Generation).**
*What:* before asking the AI to write, first **retrieve** the most relevant facts and hand them to it. *Here:* if you paste a longer "career history," `rag.py` finds the pieces most relevant to *this* job and adds them to the tailoring context (still guardrail-checked). *Why:* your full background is bigger than one CV; RAG surfaces the relevant parts per job without stuffing everything into the prompt.

**Embeddings.**
*What:* turning text into a list of numbers (a "vector") so similar meanings sit close together. *Here:* `GeminiEmbeddings` (real, hosted) or `TfidfEmbeddings` (local fallback) in `rag.py`. *Why:* it's how the computer measures "which experience is most relevant to this job."

**Vector store + cosine similarity + retriever.**
*What:* a vector store holds embeddings and finds the closest ones; "cosine similarity" measures closeness by angle between vectors; a retriever returns the top-k closest. *Here:* LangChain's `InMemoryVectorStore` + `as_retriever(k=4)`. *Why:* it's the mechanism that picks the most relevant career chunks.

**LangChain.**
*What:* a toolkit of standard building blocks for LLM apps (embedders, vector stores, retrievers, chains). *Here:* used **only** for the RAG retrieval chain (`langchain-core`), not to wrap everything. *Why:* it gives battle-tested abstractions where they help, without over-engineering the rest.

**Gemini vs TF-IDF embeddings (pluggable).**
*What:* two ways to make embeddings — a hosted model (Gemini `text-embedding-004`) or a local math technique (TF-IDF). *Here:* if `GEMINI_API_KEY` is set it uses Gemini; otherwise the local TF-IDF fallback, so RAG works with no key. *Why:* the real model is better; the fallback keeps the feature testable and resilient.

### F. Classic ML (the deterministic skill-match)

**TF-IDF + tokenization + keyword coverage.**
*What:* tokenization splits text into words; TF-IDF weighs words by importance; "keyword coverage" checks which of a job's requirement words actually appear in your CV. *Here:* `skillmatch.py` uses scikit-learn's analyzer (lowercase, tokenize, drop common "stop words") and marks a requirement **covered** if at least half its meaningful terms appear in your CV. *Why:* a **deterministic, non-AI second opinion** next to the LLM's fit score — same input always gives the same, explainable answer. *(Lesson: an earlier version compared each short requirement to the *whole* CV with cosine similarity, which diluted the signal and wrongly flagged real skills like "JavaScript" as missing — term-presence is more accurate here.)*

### G. Data & authentication

**Database, SQL, Postgres, Supabase.**
*What:* a database stores data permanently; SQL is the query language; Postgres is a popular SQL database; Supabase hosts one for free. *Here:* accounts and saved applications live in Postgres (via Supabase) in production. *Why:* to remember users and their tracked jobs across devices and restarts.

**SQLAlchemy (ORM) + "create tables".**
*What:* an ORM lets you work with database rows as Python objects instead of raw SQL. *Here:* `db_sql.py` defines `User` and `TrackedApplication` classes; the same code runs on **SQLite locally** (a file, zero setup) and **Postgres in production** (just change `DATABASE_URL`). *Why:* write once, test locally without a database, deploy to a real one.

**Password hashing (bcrypt).**
*What:* storing a scrambled, one-way version of a password, never the password itself. *Here:* `security.py` hashes with bcrypt on register and compares on login. *Why:* if the database ever leaked, real passwords wouldn't be exposed.

**JWT + Bearer auth.**
*What:* on login the server gives you a signed token (JWT); you send it back as `Authorization: Bearer <token>` to prove who you are. *Here:* `security.py` issues/verifies tokens; protected endpoints require one. *Why:* the server doesn't need to store sessions — the signed token *is* the proof.

**User-scoping / IDOR.**
*What:* IDOR = "Insecure Direct Object Reference," where you could read someone else's data by guessing an ID. *Here:* every tracker query filters by *your* user id, so you can only ever see/edit your own applications (returns 404 for others'). *Why:* privacy and security — a classic bug this project deliberately avoids (and QA verified).

**Connection pooling / IPv4 vs IPv6 (a real deploy lesson).**
*What:* a "pooler" reuses database connections; Supabase's direct connection is IPv6-only, which the host (Render) can't reach. *Here:* the fix was using Supabase's **session pooler** URL. *Why:* real-world ops detail — the wrong connection string silently fails.

### H. Search

**Elasticsearch (full-text search) + inverted index.**
*What:* a search engine built for fast text search; an "inverted index" maps each word to the documents containing it (like a book's index). *Here:* `search.py` indexes your saved applications and searches them; the frontend has a search box in the tracker. *Why:* as your tracker grows, fast keyword search over titles/companies/analysis is genuinely useful.

**Fallback search.**
*What:* if Elasticsearch isn't configured or is down, search still works via a simple database "contains" query. *Here:* `search_apps` raises a signal that triggers the DB fallback. *Why:* the feature works with or without the extra service.

### I. Deployment & operations

**Git + GitHub.**
*What:* Git tracks every change (commits); GitHub hosts the code online. *Here:* each circle is a commit; `github.com/NitaiEdelberg/applylens`. *Why:* history, backup, collaboration, and it triggers deploys.

**Render + Netlify + environment variables.**
*What:* Render hosts the backend; Netlify hosts the frontend. "Env vars" are secret settings (API keys, DB URLs) kept out of the code. *Here:* `GROQ_API_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`, `ELASTICSEARCH_URL` live in Render's settings. *Why:* secrets never belong in the code/repo.

**CI/CD (auto-deploy).**
*What:* pushing code automatically builds and releases it. *Here:* a push to GitHub auto-deploys the backend (Render) and frontend (Netlify). *Why:* ship safely and often with no manual steps.

**GitHub Actions (the keep-alive cron).**
*What:* GitHub's free automation that can run on a schedule. *Here:* `.github/workflows/keepalive.yml` pings the backend every 3 days so the free Supabase database doesn't pause after inactivity. *Why:* keeps the app working months later at zero cost.

**Cold starts.**
*What:* free servers "sleep" when idle and take ~40s to wake. *Here:* the frontend shows a friendly "waking up the server…" state with automatic retries instead of an error. *Why:* turns a free-tier limitation into a thoughtful UX detail.

**Python version pinning / wheels (a real deploy bug we hit).**
*What:* a "wheel" is a pre-built package; some packages have wheels only for certain Python versions. *Here:* pinning the backend to **Python 3.12** (`backend/.python-version`) so scikit-learn/scipy install from wheels — Python 3.13 had no wheel and the build failed. *Why:* real lesson — dependency/runtime mismatches break deploys silently.

**File parsing (PDF/DOCX upload).**
*What:* extracting text from uploaded documents. *Here:* `resume.py` uses `pypdf` (PDF) and `python-docx` (Word) to turn an uploaded résumé into text for the pipeline. *Why:* pasting is friction; uploading is what people expect.

---

## 5. What the whole thing demonstrates (for interviews)

- **Applied AI:** LLM orchestration, structured output, an LLM guardrail, a self-correction loop, and **measured evals**.
- **RAG:** embeddings, a vector store, retrieval, LangChain — with a resilient local fallback.
- **Classic ML:** a deterministic TF-IDF/keyword signal alongside the LLM.
- **Full-stack:** React frontend, FastAPI backend, REST APIs, async concurrency.
- **Data & security:** SQL/Postgres, an ORM, password hashing, JWT auth, user-scoping (no IDOR).
- **Search:** Elasticsearch with a database fallback.
- **DevOps:** Git/GitHub, CI/CD auto-deploy, environment secrets, a keep-alive cron, cold-start UX, and several real deploy bugs found and fixed.
- **Engineering judgment:** graceful degradation everywhere, and features scoped to ship on free tiers.

**How to talk about it in one line:** *"I built and deployed an AI job-hunt product with a fact-checking guardrail, a self-correcting generation loop, measured evals, RAG with LangChain, a deterministic ML signal, full-stack accounts, and Elasticsearch — all resilient on free infrastructure."*
