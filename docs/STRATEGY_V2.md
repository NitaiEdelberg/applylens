# ApplyLens — Strategy V2

_CTO + GTM plan, 2026-07-12. Goal: evolve ApplyLens into a product that (a) genuinely improves for the job-seeker, (b) showcases the skills a **Software Engineer** and **AI Solutions Engineer** are hired for — LangChain, more ML, RAG, Elasticsearch — and (c) stays shippable on free tier (Netlify + Render 512MB + free external accounts, no credit card where possible). Every technology below earns its place with a real use case or is explicitly called out as optional showcase._

Grounding invariants that are **non-negotiable** through all of this: the fabrication guardrail, the "never fabricate / degrade honestly" trust story, and the eval-measured accuracy number. Nothing below is allowed to weaken them.

---

## 1. Positioning / Uniqueness (GTM)

### One-sentence positioning

> **ApplyLens is a job-hunt workspace, not a chat box: it runs your real CV against every job through a fabrication guardrail that labels each tailored bullet "verified against your CV" or "not supported" — with the evidence, a self-correcting fix, a measured accuracy number, and a tracker across every application — the trust, workflow, and proof a raw ChatGPT/Claude paste structurally cannot give you.**

### Top differentiators vs. "just paste your CV + job post into ChatGPT/Claude"

Each is tied to a real, shipped feature — no hype:

| # | Differentiator | Real feature (file) | Why chat can't do it |
|---|---|---|---|
| 1 | **Trust you can see** — every tailored bullet is labeled *verified* (with the CV evidence) or *not supported* (with the specific reason), inline. | `grounding.py` `check_grounding`, `GuardrailPanel.jsx` | Chat will happily write "Led a team of 8 at Google." It has no structured verdict object and no independent fact-check against your source CV. |
| 2 | **A self-correcting repair loop** — a flagged bullet can be regenerated *conditioned on the exact failure reason*, then **independently re-verified** by the same fact-checker, bounded and honest (stays red if the CV genuinely can't back it). | `tailor.py` `regenerate_bullet`, `/api/regenerate-bullet` | Chat regenerates on request but doesn't re-grade its own fix against the CV, doesn't bound the retry, and won't degrade honestly — it'll just assert a new claim. |
| 3 | **Measured accuracy** — the guardrail is graded by a labeled eval harness and the number (precision/recall) is surfaced in the UI. | `evals/run_evals.py`, `TrustPanel.jsx` | Chat gives you vibes; ApplyLens gives you a number you can point an interviewer at. |
| 4 | **A workflow across many jobs** — analyses persist to a tracker and move applied → interviewing → offer; re-open any past analysis with no LLM call. | `tracker.js`, `Tracker.jsx` | Chat loses everything on refresh. There is no pipeline, no system of record. |

Also real and chat-proof: the **cover letter is grounded too** — only the letter's factual self-claims are extracted and checked, so boilerplate ("I'm excited to apply") is never false-flagged (`check_cover_letter`).

### Target user

- **Primary:** an active job-seeker — especially technical / engineering candidates — applying to *many* roles, who wants tailored materials that are **not fabricated** and a **system of record** across the search. The pain is real: hallucinated resume claims get caught in interviews, and chat loses your history every session.
- **Secondary (and the honest business reason this repo exists):** the founder, using ApplyLens as an **applied-AI portfolio piece** for SWE / AI-SE interviews — structured LLM I/O, a user-facing guardrail, a self-correction loop, evals, and (via this plan) RAG, retrieval orchestration, an ML signal, auth+DB, and search.

### Honest gaps (where we are *not yet* differentiated)

- **No accounts / no cross-device.** The tracker is browser-local (`localStorage`); clear your cache or switch devices and it's gone. (Circle 3 fixes this.)
- **Paste-only input.** No resume file upload yet — a friction point vs. every real tool. (Circle 1 fixes this.)
- **Single CV, single shot.** We tailor one pasted CV per job. We don't yet retrieve from a broader body of your real work — which is exactly where RAG becomes honest instead of theater. (Circle 4.)
- **Small eval set (n=17).** The accuracy number is real but thin; it should grow toward 30–50 labeled statements and the framing must stay honest.
- **Single-family judge.** Generation and grounding both run on the same Groq model family — there's no independent judge model, so the guardrail shares the generator's blind spots.
- **Not yet live-linked.** Per the release notes, no deployed demo URL in the README — the single cheapest credibility upgrade.

---

## 2. Answers to the CEO's two questions

### Q1 — Tracker persistence: localStorage → per-person, cross-device

**Today:** `tracker.js` stores records in `localStorage` under a versioned key. It's per-browser, no accounts, no sync. Good for a zero-infra demo; wrong for "my applications follow me across devices."

**What "per-person" requires:** (1) **auth** (identify the person), and (2) a **server-side DB** keyed by user id. That means one external account. The free-tier / credential trade-offs:

| Option | What you get free (2026, no credit card) | Trade-off |
|---|---|---|
| **Supabase** *(recommended)* | Postgres 500 MB · **Auth 50k MAU** (email + social OAuth + anonymous) · storage · **pgvector built in** · 2 projects. No CC. | Free project is **paused after ~1 week of inactivity** — a real gotcha for a portfolio app that sits idle; first request after a pause is slow. Mitigate with a light keep-alive or accept the wake delay (we already have cold-start UX). |
| **Neon** + Neon Auth | Postgres 0.5 GB/project · **Neon Auth 60k MAU** · **scale-to-zero** (wakes automatically) · branching · 100 projects. No CC. | Purest Postgres + auto-wake (no manual keep-alive). Slightly more wiring than Supabase's batteries-included SDK. Also has pgvector. |
| **Firebase (Firestore + Auth)** | Generous auth + NoSQL free tier. | NoSQL, not SQL — weaker "I designed a relational schema" story; Google-specific SDK lock-in. |

**Recommendation: Supabase.** One free account gives **auth + Postgres + pgvector**, which means Circle 3 (accounts) and Circle 4 (RAG vector store) share a **single credential** — you don't stand up a separate vector DB later. The only real cost is the 1-week idle pause; Neon is the fallback if that pause becomes annoying (it wakes on demand). Either way this is **credential-gated** — it cannot be built without the CEO creating the account.

Migration is clean: keep `tracker.js` as the interface, swap its four functions (`loadApps`/`saveApp`/`updateStatus`/`deleteApp`) from `localStorage` to authenticated Supabase calls, and offer a one-time "import my local applications" on first login so nobody loses their existing tracker.

### Q2 — Resume file upload (instead of pasting)

**Goal:** user drops a PDF/DOCX resume; we extract text into the existing `cv_text` that already flows through `extract`/`fit`/`tailor`/`grounding`. **No external credential needed either way** — this is pure parsing.

| Approach | How | Effort | Render 512MB impact |
|---|---|---|---|
| **Server-side parse** *(recommended)* | New `POST /api/upload-cv` accepts multipart; parse **PDF with `pypdf`** (pure-Python, MIT) or `pdfminer.six`, **DOCX with `python-docx`**; return extracted text. Frontend swaps the CV textarea for a drop zone that posts the file and fills the text (still editable). | ~0.5 day | Negligible. `pypdf`/`python-docx` are small pure-Python libs (a few MB), no native model, no torch. Safe on 512MB. |
| **Client-side parse** | Extract in the browser with `pdf.js` (PDF) + `mammoth.js` (DOCX); backend never sees the file. | ~0.5 day | **Zero** backend memory — attractive given the 512MB budget. But bundles ship to the browser and it's a weaker "I handled file uploads/multipart" resume signal. |

**Recommendation: server-side** (`pypdf` + `python-docx`). It centralizes parsing in one place, is the stronger engineering-story (multipart handling, content-type validation, size limits), and the memory cost is trivial. Keep paste as a fallback and always let the user **edit the extracted text** before analyzing (OCR/columns can garble PDFs). Add basic guards: max file size (e.g. 2 MB), allowed content types, and a friendly error when extraction yields empty text (scanned/image-only PDF).

**This is BUILDABLE NOW** — no new account or key.

---

## 3. Sequenced 5-circle roadmap

Mapping the CEO's six named topics — **resume upload, more ML, multi-user tracker, RAG, LangChain, Elasticsearch** — onto 5 circles (one feature-set each). LangChain folds into the RAG circle, where retrieval orchestration is genuinely idiomatic rather than gratuitous (see §4).

**Build order rule:** BUILDABLE-NOW circles first (no new credential), then credential-gated in increasing infra weight. Circle 3 (Supabase) is deliberately sequenced before Circle 4 so its pgvector serves the RAG store — two topics, one credential.

```
BUILDABLE NOW  ──►  1. Resume File Upload      (no cred)
                    2. ML Skill-Match Signal   (no cred)
NEEDS A CRED   ──►  3. Accounts + Cloud Tracker (Supabase/Neon)
                    4. RAG Career Corpus + LangChain (embeddings API + pgvector)
                    5. Elasticsearch Hybrid Search  (ES instance) — optional showcase
```

---

### Circle 1 — Resume File Upload  · **BUILDABLE NOW (no new credential)**

**Title.** Drop your resume as a file (PDF/DOCX), not a paste.

**Why.**
- *User value:* removes the single biggest input-friction point; nobody keeps their CV as plain text.
- *SWE/AI-SE resume value:* file upload, multipart handling, content-type/size validation, document parsing — bread-and-butter backend engineering the current paste-only app doesn't demonstrate.
- *Why chat can't do it (as well):* chat can read a pasted file, but it doesn't own the parse, doesn't validate, and doesn't feed a structured downstream pipeline. This is product plumbing, not a differentiator on its own — it's table stakes that unblocks everything else.

**Scope — in:** `POST /api/upload-cv` (multipart) → text via `pypdf` (PDF) + `python-docx` (DOCX); size/type guards; empty-extraction error. Frontend drop zone that fills the (still-editable) CV field. **Out:** OCR for scanned PDFs; parsing formatting/layout; storing the file; DOCX styling.

**Acceptance criteria.**
- Uploading a text-based PDF or DOCX returns extracted text; the CV field is populated and remains editable.
- Non-PDF/DOCX or oversized files return a friendly 400, never a 500.
- An image-only/empty PDF returns a clear "couldn't read text from this file — paste it instead" message.
- Paste still works unchanged; the whole existing `analyze` pipeline is untouched downstream of `cv_text`.

**Affected files.** `backend/requirements.txt` (`pypdf`, `python-docx`), `backend/src/server.py` (+ maybe `services/parse.py`), `backend/src/schemas.py`, `frontend/src/api.js`, `frontend/src/App.jsx`, `frontend/src/styles.css`, `README.md`.

**Dependencies/credentials CEO must provide.** **None.** Pure-Python libs, existing infra.

**Risk.** Low. Memory impact on Render is negligible (small pure-Python libs, no model). Only real risk is garbled text from complex PDF layouts — mitigated by keeping the extracted text editable.

---

### Circle 2 — ML Skill-Match Signal  · **BUILDABLE NOW (no new credential)**

**Title.** A cheap, explainable, non-LLM skill-coverage signal ("more ML," done deployably).

**Why.**
- *User value:* a second, deterministic opinion next to the LLM fit score — a **skill-coverage %** and an explicit **gap list** computed from the text, that doesn't change run-to-run and is cheap enough to run on every keystroke if wanted.
- *SWE/AI-SE resume value:* real, classical ML you built and deployed — TF-IDF vectorization + cosine similarity (optionally a small logistic-regression **calibrator** trained on the eval set to align the LLM's 0–100 score with labeled outcomes). Shows you can add an ML signal that is explainable and CPU-cheap, and that you know *when not to reach for a 70B model.*
- *Why chat can't do it:* chat gives one probabilistic narrative score; this adds an independent, reproducible, inspectable numeric signal with a transparent method — the kind of measured second-opinion a chat window doesn't produce.

**Scope — in:** `scikit-learn` TF-IDF over CV bullets vs. extracted JD requirements (`must_haves`/`nice_to_haves`/`stack`); cosine match per requirement → coverage score + gap list; surface beside `FitGauge`. Optional: a tiny logistic-regression calibrator persisted as a pickled model, trained offline from `evals/`. **Out:** neural embeddings / sentence-transformers / torch (see Risk); any GPU; per-user training.

**Acceptance criteria.**
- Given a CV + extracted requirements, returns a coverage score (0–100) and a list of unmatched requirements, deterministically (same inputs → same output).
- Runs in-process with no external API call and no LLM round-trip.
- Displayed as a distinct signal, clearly labeled as a heuristic match — never overriding or masquerading as the LLM fit score.
- Cold-start and steady-state memory stay within the Render free tier (see Risk).

**Affected files.** `backend/requirements.txt` (`scikit-learn`, `numpy`), new `backend/src/services/skillmatch.py`, `backend/src/server.py` (fold into `/api/analyze` or a new endpoint), `frontend/src/App.jsx` / a small component, `frontend/src/styles.css`.

**Dependencies/credentials CEO must provide.** **None.**

**Risk.** **Memory is the watch-item.** `scikit-learn` + `numpy` is CPU-only and fits (~100–200 MB) on the 512 MB Render instance — acceptable, but verify it doesn't push total RSS past the limit alongside FastAPI. **Do NOT use `sentence-transformers`/`transformers`/`torch` here** — they will OOM or blow the cold-start on 512 MB. If neural similarity is ever wanted, get it from a hosted embeddings API (Circle 4), not a local model.

---

### Circle 3 — Accounts + Cloud Tracker  · **NEEDS A CREDENTIAL (Supabase or Neon)**

**Title.** Per-person, cross-device tracker (auth + Postgres).

**Why.**
- *User value:* your applications follow you across devices and survive a cache clear — the tracker becomes a real system of record, not a browser artifact.
- *SWE/AI-SE resume value:* auth, per-user data isolation (row-level security), a relational schema, and a client→DB migration — the "I shipped a real multi-tenant app" story the current localStorage version can't tell.
- *Why chat can't do it:* chat has no persistence and no concept of *you*; a per-user pipeline of tracked applications is structurally impossible in a chat window.

**Scope — in:** Supabase Auth (email + one OAuth provider); an `applications` table keyed by `user_id` with row-level security; migrate `tracker.js` from `localStorage` to authenticated Supabase calls behind the same interface; a one-time "import my local applications" on first login. **Out:** teams/sharing; roles/permissions beyond "owns their rows"; server-side rendering; password reset flows beyond Supabase defaults.

**Acceptance criteria.**
- A signed-in user sees the same tracker on two different browsers/devices.
- A user can never read another user's applications (enforced by RLS, not just client filtering).
- Existing localStorage records import once on first login without loss.
- Signed-out experience still works for a one-off analyze (auth gates only the tracker/persistence, not the core analyze).
- Corrupt/again-unavailable network degrades gracefully (read-only or clear error), never a crash.

**Affected files.** `frontend/src/tracker.js` (swap storage impl), `frontend/src/App.jsx` (auth state, sign-in UI), `frontend/src/api.js` or new `frontend/src/supabase.js`, `frontend/package.json` (`@supabase/supabase-js`), env config for keys, `README.md`.

**Dependencies/credentials CEO must provide.** **Supabase account** → project URL, anon (publishable) key, and service-role key (kept server-side/secret). Free, no credit card. *(Fallback: Neon + Neon Auth if the Supabase idle-pause is a problem.)*

**Risk.** Free-tier **idle pause** (Supabase pauses after ~1 week inactive) → slow first request after dormancy; our existing cold-start UX absorbs it, or add a light keep-alive. Keys must be handled correctly: anon key is public, **service-role key must never ship to the browser.** Low compute/memory risk (DB is external, not on Render).

---

### Circle 4 — RAG Career Corpus + LangChain  · **NEEDS A CREDENTIAL (embeddings API + vector store)**

**Title.** Tailor from your *whole* career, not one pasted CV — retrieval-grounded, orchestrated with LangChain.

**Why.**
- *User value:* upload many artifacts once — past resumes, project write-ups, a brag doc, prior cover letters — and for each job ApplyLens **retrieves the most relevant real experiences** to tailor from and to ground against. This makes bullets richer *and* keeps them honest, because grounding now points at retrieved real evidence.
- *SWE/AI-SE resume value:* a genuine, defensible **RAG** pipeline (chunk → embed → store → retrieve → grounded-generate) plus **LangChain** used where it earns its place (a composed retriever→prompt→LLM→parser chain). This is the single most sought-after applied-AI competency.
- *Why chat can't do it:* a chat paste is limited to what you paste this session; it can't index and retrieve across a persistent, per-user corpus that exceeds the context window, and it can't re-ground generated claims against the specific retrieved chunks. (See §4 for the honest "is RAG even useful here" analysis — the answer is *only in this multi-artifact form*.)

**Scope — in:** ingest multiple CV/career documents per user → chunk → embed (hosted API) → store vectors in **Supabase pgvector** (reuse Circle 3's DB) → per-job retrieval of top-k relevant chunks → feed retrieved evidence into tailoring + grounding. A **LangChain** retrieval chain (LCEL: `retriever | prompt | llm | parser`) expresses this composition. **Out:** ripping out the existing clean `llm.py`/service functions and rewrapping everything in LangChain (that's gratuitous — see §4); multimodal/image embeddings; cross-user retrieval.

**Acceptance criteria.**
- A user can add several documents; they're chunked, embedded, and stored with `user_id` isolation.
- For a given job, retrieval returns the top-k most relevant chunks, and tailored bullets are grounded against retrieved evidence (guardrail invariant preserved — still "verified/not-supported with reason").
- Retrieval is scoped to the requesting user only.
- Embedding calls stay within the free daily quota, or fail gracefully with a clear message.
- The existing single-paste flow still works unchanged for users who don't build a corpus.

**Affected files.** `backend/requirements.txt` (`langchain-core`/`langchain`, embeddings client), new `backend/src/services/rag.py` (chunk/embed/retrieve chain), `backend/src/services/tailor.py` (accept retrieved context), `backend/src/server.py` (ingest + retrieve endpoints), pgvector schema/migration, frontend corpus-management UI, `README.md`.

**Dependencies/credentials CEO must provide.**
- **Embeddings API key** — **Google Gemini Embedding** recommended (1,500 requests/day free, no credit card). Alternatives: Jina (1M tokens/month), Cohere (free tier, retrieval-tuned).
- **Vector store** — **reuse Supabase pgvector from Circle 3 (no new account).** Alternative if not on Supabase: **Qdrant Cloud** (1 GB free forever, no CC) or **Zilliz/Milvus** free tier.

**Risk.** **Do not run a local embedding model on Render** — offload embeddings to the hosted API so the 512 MB instance never loads torch. Watch the **free embedding quota** (1,500/day is fine for one user building a corpus; batch on ingest, not per-request). Keep LangChain scoped to the retrieval chain so it doesn't bloat the deploy or obscure the existing clean code. Latency: retrieval adds a round-trip — acceptable, and cached embeddings mean re-analysis doesn't re-embed.

---

### Circle 5 — Elasticsearch Hybrid Search  · **NEEDS A CREDENTIAL (ES instance) · OPTIONAL SHOWCASE**

**Title.** Full-text + hybrid search across your applications and a JD corpus.

**Why.**
- *User value:* once a user has many tracked applications (and, with Circle 4, a document corpus), fast keyword/hybrid search — "show every backend role where I flagged Kubernetes" — becomes useful.
- *SWE/AI-SE resume value:* Elasticsearch/OpenSearch is a widely-requested keyword on job posts; a **hybrid BM25 + vector** search is a strong, concrete demonstration.
- *Why chat can't do it:* chat has no index over your persistent history; it can't do BM25 ranking or hybrid retrieval across a corpus.

**Honest caveat (read §4):** at the scale a single job-seeker generates (tens–low-hundreds of records), **Postgres full-text search (`tsvector`) or pgvector already covers this** with **no new credential.** Elasticsearch here is **primarily a resume-keyword showcase**, not a product necessity — and it needs a separate ES instance. Ship the Postgres-FTS version first; add ES only if the resume specifically needs the word "Elasticsearch."

**Scope — in (if pursued):** index applications + corpus into Elasticsearch/OpenSearch; a search UI; hybrid BM25 + vector ranking. **Out:** replacing Postgres as the source of truth (ES is a search index, not the DB); analytics dashboards; log/observability use of ES.

**Acceptance criteria.**
- Keyword search over the user's applications returns ranked, user-scoped results.
- (If hybrid) combines BM25 with vector similarity and returns sensibly merged ranking.
- Index stays in sync with the Postgres source of truth on create/update/delete.
- Falls back cleanly to Postgres FTS if the ES instance is unavailable.

**Affected files.** New `backend/src/services/search.py`, indexing hooks on tracker writes, `backend/src/server.py` (search endpoint), `backend/requirements.txt` (`elasticsearch`/`opensearch-py`), frontend search UI, `README.md`.

**Dependencies/credentials CEO must provide.** **An Elasticsearch/OpenSearch instance** — e.g. **Bonsai** or **Elastic Cloud** (14-day trials, no permanent no-CC free-forever tier in 2026), or self-host (needs infra). **This is the one topic without a solid free-forever, no-credit-card option** — flag it explicitly.

**Risk.** **Do not run Elasticsearch on the 512 MB Render instance** — the JVM alone won't fit; ES must be external. Cost/credential risk is real (no clean free tier). Sync complexity (dual-write to Postgres + ES) adds failure modes. Given all this, **recommend Postgres FTS first, ES only as a deliberate showcase.**

---

## 4. Honest tech calls

**RAG — is it genuinely useful here?**
**Not over a single short CV** — a resume fits comfortably in the Groq model's context, so "RAG over your one pasted CV" is theater that adds latency and infra for nothing. **It becomes genuinely useful in exactly one form:** a **multi-artifact career corpus** (many past resumes, project write-ups, brag docs, prior cover letters) that *exceeds* the context window, where per-job retrieval surfaces the most relevant real experiences and the guardrail grounds against the retrieved chunks. That's a real retrieval problem and it *strengthens* the trust story. **Free stack:** hosted **Gemini embeddings** (1,500/day, no CC) + **Supabase pgvector** (reuse the Circle-3 DB — no new store). This is why Circle 4 is gated on a corpus, not shipped for single-CV analysis.

**LangChain — where it earns its place.**
The existing `llm.py` is a clean, well-typed async httpx wrapper; **ripping it out to rewrap `extract`/`fit`/`tailor` in LangChain would be a gratuitous, resume-driven downgrade** and I'd advise against it. LangChain earns its place in **exactly one spot: the RAG retrieval chain** (Circle 4), where `retriever | prompt | llm | parser` composition (LCEL) is idiomatic, legible, and the thing interviewers mean when they say "LangChain." Use `langchain-core` there; leave the rest of the codebase alone.

**Elasticsearch — real use vs. lighter alternative.**
Real use exists only *at scale* (large searchable corpus). At a single job-seeker's scale, **Postgres full-text search (`tsvector`) or pgvector already delivers the search feature with no new credential.** Elasticsearch is a **resume-keyword showcase** here, not a product need, and — flagged clearly — **it requires a separate ES instance** (Bonsai/Elastic Cloud trial; no clean free-forever no-CC tier in 2026) and must never run on the 512 MB Render box. Ship Postgres FTS first; add ES deliberately if the keyword matters for interviews.

**"More ML" — a concrete, deployable idea.**
A **CPU-only, `scikit-learn` skill-match signal**: TF-IDF over CV bullets vs. extracted requirements + cosine similarity → an explainable coverage score and gap list, optionally a small logistic-regression calibrator trained on the eval set. It's deterministic, cheap, and — crucially — **fits on 512 MB** (no torch). This is the honest "more ML" that ships, versus `sentence-transformers`/`transformers`, which will OOM the free Render tier. Neural similarity, if ever wanted, comes from the hosted embeddings API (Circle 4), never a local model.

---

## 5. What we need from you (CEO) — credentials/accounts

Circles 1 and 2 need **nothing new** — they ship on the existing Groq key + Render/Netlify. The credential-gated circles need:

| Circle | Account / key needed | Free in 2026? | Notes |
|---|---|---|---|
| **3 — Accounts + Cloud Tracker** | **Supabase** project → URL + anon key + service-role key | ✅ Free, **no credit card** | One account also provides pgvector for Circle 4. Idle-pause after ~1 wk. *(Alt: Neon + Neon Auth, auto-wake.)* |
| **4 — RAG Career Corpus** | **Google Gemini** (AI Studio) embeddings API key | ✅ Free (1,500 req/day), **no credit card** | Alts: Jina (1M tok/mo), Cohere (retrieval-tuned). |
| **4 — vector store** | **Reuse Supabase pgvector** (no new account) | ✅ | Alt only if not on Supabase: **Qdrant Cloud** (1 GB free forever, no CC) or Zilliz/Milvus. |
| **5 — Elasticsearch** *(optional showcase)* | **Elasticsearch/OpenSearch instance** — Bonsai or Elastic Cloud | ⚠️ **Trials only** (14-day, no permanent no-CC free tier) | The **only** topic without a clean free-forever option. Recommend Postgres FTS first; ES only if the keyword is needed. |

**Bottom line:** two free, no-credit-card accounts (**Supabase** + **Google Gemini**) unlock Circles 3 and 4 — accounts, cloud tracker, and RAG. Elasticsearch (Circle 5) is the only credential with no clean free tier and is optional.

---

## Sources (2026 free-tier verification)

- Embeddings free tiers: [EdenAI — Best Free Embedding Models & APIs 2026](https://www.edenai.co/post/top-free-embedding-tools-apis-and-open-source-models), [Jina Embeddings](https://jina.ai/embeddings/), [Grizzly Peak — Every AI API with a Free Tier 2026](https://www.grizzlypeaksoftware.com/articles/p/every-ai-api-with-a-free-tier-in-2026-the-developers-cheat-sheet-jl33ach0)
- Vector stores: [MarkTechPost — Best Vector Databases 2026](https://www.marktechpost.com/2026/05/10/best-vector-databases-in-2026-pricing-scale-limits-and-architecture-tradeoffs-across-nine-leading-systems/), [Zilliz Cloud Free Tier](https://zilliz.com/zilliz-cloud-free-tier), [Infrabase — Vector DB pricing 2026](https://infrabase.ai/compare/vector-databases)
- Postgres + auth: [Koyeb — Top PostgreSQL Free Tiers 2026](https://www.koyeb.com/blog/top-postgresql-database-free-tiers-in-2026), [Neon vs Supabase Free Tier 2026](https://agentdeals.dev/neon-vs-supabase), [Supabase Free Tier Limits 2026](https://aiagencyplus.com/supabase-free-tier-limits/)
- Elasticsearch hosting: [Bonsai](https://bonsai.io/), [HostAdvice — Free Elasticsearch Hosting Jun 2026](https://hostadvice.com/web-hosting/elasticsearch-hosting/free/), [Slant — Bonsai vs Elastic Cloud 2026](https://www.slant.co/versus/567/569/~bonsai_vs_elastic-cloud)
