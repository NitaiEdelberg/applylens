# ApplyLens 🔎

An AI copilot for the job hunt. Paste a job description and your CV, and ApplyLens:

1. **Extracts** the posting into structured requirements (must-haves, nice-to-haves, stack)
2. **Scores your fit** against the role — strictly evidence-based (matched / partial / missing)
3. **Tailors** resume bullets + a cover letter, **grounded** in your real CV
4. **Guards against fabrication** — a grounding check flags any generated claim your CV doesn't support

Built as a real tool *and* a showcase of applied-AI engineering: structured LLM extraction, LLM-as-judge scoring, grounded generation, an anti-hallucination **guardrail**, and an **eval harness** with precision/recall.

## Architecture

```
React (Vite)  ──►  FastAPI  ──►  Groq (OpenAI-compatible LLM)
                     │
   /api/extract  ──  extract.py     JD text     → structured requirements
   /api/fit      ──  fit.py         JD + CV     → evidence-based fit score
   /api/tailor   ──  tailor.py      JD + CV     → tailored bullets + cover letter
                        └── grounding.py  each bullet → supported? (guardrail)
evals/run_evals.py     grounding guardrail → accuracy + fabrication precision/recall
```

## Tech stack

**Backend:** Python · FastAPI · httpx · Groq (`llama-3.3-70b-versatile`)
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
cd backend && pytest                       # smoke tests (no key needed)
GROQ_API_KEY=... python evals/run_evals.py # grounding guardrail metrics
```

## API

| Endpoint | Body | Returns |
|---|---|---|
| `GET /health` | — | `{"status":"ok"}` |
| `POST /api/extract` | `{jd_text}` | structured requirements |
| `POST /api/fit` | `{jd_text, cv_text}` | `overall_score`, matched/partial/missing, summary |
| `POST /api/tailor` | `{jd_text, cv_text}` | `bullets`, `cover_letter`, `grounding[]`, `flagged_count` |
| `POST /api/analyze` | `{jd_text, cv_text}` | `{job, fit, tailor}` — runs all three concurrently in one call |

## Roadmap

- Application tracker (Kanban: applied → interview → offer)
- Embedding-based retrieval over CV bullets (pgvector) for larger CVs
- Persist analyses (Postgres) and a per-provider fallback for the LLM
- Deploy: backend on Render, frontend on Netlify

## Development team (subagents)

This repo defines a small agent team under `.claude/agents/` — `product-manager`,
`developer`, `qa-tester`, and `bug-fixer` — used to plan, build, test, and fix
features. See each file for its role and scope.
