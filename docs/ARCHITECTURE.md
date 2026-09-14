# ApplyLens: how a request actually works

One page, written to be talked through out loud. It follows a single call to
`POST /api/analyze` from the browser to the answer, and says what can go wrong
at each step and what happens when it does.

## The whole thing at a glance

```
browser (Netlify)
    │  POST /api/analyze  { jd_text, cv_text, career_text? }
    ▼
FastAPI (Render free instance, 512 MB, sleeps after 15 min idle)
    │
    ├─ 0. cache lookup ─────── fingerprint(jd, cv, career) → hit? return, done
    │
    ├─ 1. redact ──────────── strip email / phone / ID / address / social links
    │                          from the CV, keep a map to put them back
    │
    ├─ 2. screen ──────────── local injection patterns + JailbreakAPI (fails open)
    │
    ├─ 3. three stages, concurrently ───────────────────────────────┐
    │      extract   JD → structured requirements        (1 model call)
    │      fit       CV vs JD → score + evidence         (1 model call)
    │      tailor    CV + JD → bullets + cover letter    (1 model call)
    │                    └─ then, concurrently:
    │                         ground bullets             (1 model call)
    │                         ground cover-letter claims (2 model calls)
    │                                                                │
    ├─ 4. skill_match ─────── deterministic term coverage, no model ─┘
    │
    ├─ 5. restore ─────────── put the personal details back into the answer
    │
    └─ 6. cache + trace ───── store the result, attach the trace, return
```

With a career corpus supplied, step 3 changes shape: `extract` and `fit` run
first, then retrieval picks four paragraphs, and `tailor` grounds against CV +
those paragraphs. Retrieval has to finish before tailoring, because the
retrieved text becomes part of the source of truth the guardrail checks against.

## The pieces, and why each exists

**`llm.py` — everything that touches Groq.** Model fallback chain, retries with
jitter, a circuit breaker, schema-constrained decoding, and cassette
record/replay. It exists as one file because every one of those concerns is
"what do we do when the model API misbehaves", and scattering them across the
services is how you end up with three different retry policies.

**`services/grounding.py` — the guardrail.** Takes generated statements and the
CV, returns a verdict per statement with evidence or an issue. It is a separate
model call at temperature 0, deliberately not the same call that generated the
text: asking a model to mark its own homework produces homework marked well.

**`services/skillmatch.py` — the second opinion.** No model at all. Term
coverage with morphology and a tool-to-category map, so it can disagree with
the LLM's fit score, which is the entire point of showing both.

**`services/rag.py` — retrieval over an optional career corpus.** Hosted
embeddings when a key is present, scikit-learn TF-IDF when not. The fallback is
not a stub: it is measured, and it is what CI runs.

**`trace.py` — what happened inside the request.** Stage timings, tokens, the
model that answered, one request id through the logs. Stages run concurrently,
so the current stage is a `ContextVar`: asyncio copies the context per task, and
a model call lands on the right stage without any service passing a trace
object around.

**`cache.py`, `budget.py`, `resilience.py`** — one idea each: don't repeat
identical work, don't let one request spend forever, don't hammer a dying
upstream.

## What fails, and what happens

| When this breaks | What the user gets |
|---|---|
| Groq retires the configured model | Next model in the chain answers. Nothing visible. |
| Groq rate limits (free tier: 8k tokens/min) | Retry after exactly the wait Groq states. Slower, still works. |
| Groq is down | Circuit opens after 4 failures; requests fail in milliseconds with 503 and Retry-After, instead of each paying the timeout. |
| The model returns malformed JSON | Mostly impossible now — the schema is enforced by the decoder. If the model does not support schemas, it degrades to JSON mode and the parse error is caught. |
| The request runs out of budget | Cover-letter grounding is skipped, bullets are still checked, and the response says so. |
| The embeddings key is missing | TF-IDF retrieval, recall@4 0.94 on the labelled set. |
| JailbreakAPI is asleep | Local patterns still run; the response says the remote check did not happen. |
| Postgres is unreachable | Accounts and the cloud tracker fail; analysis is unaffected — it needs no database. |

## The costs of the shape it has

**One process, in-process cache.** The cache dies when the free instance sleeps
and is not shared between instances. Correct for one box; wrong the moment
there are two, and the fix then is Redis, not a bigger dict.

**Six model calls per analysis.** That is the price of separating generation
from verification. Cutting it to four by having the generator self-report
grounding would be faster and would destroy the only property that makes the
output trustworthy.

**A free instance that sleeps.** First request of the day takes ~50 seconds.
The UI wakes the backend on page load and explains the wait rather than
pretending it is fast.

## Where the numbers come from

Everything claimed about quality is in `evals/`, and all of it runs from the
command line:

| Question | Command | Current |
|---|---|---|
| Does the coverage signal agree with a person? | `python evals/run_skillmatch_eval.py` | P 0.98 / R 1.00 on 65 labelled cases (the rule it replaced: 0.92 / 0.56) |
| Does the guardrail catch fabrications? | `python evals/run_evals.py --replay` | 95 labelled rows: accuracy 0.98, precision 0.96, recall 1.00 — 0 missed, 2 true statements wrongly flagged |
| Does retrieval find the right paragraphs? | `python evals/run_retrieval_eval.py` | recall@4 0.94, MRR 1.00, TF-IDF path |
| Is the new prompt better than the old one? | `python evals/run_prompt_ab.py` | grounded-bullet rate per version |

CI runs the three that need no key on every push.
