#!/usr/bin/env bash
# Everything that needs the model API, run one after another overnight.
#
# Strictly sequential on purpose. Groq's free tier meters tokens per minute
# ACROSS THE ACCOUNT, so two of these running at once do not go twice as fast:
# they rate-limit each other, and every retry re-sends its prompt, which counts
# against the same ceiling and keeps you limited. One at a time, paced under the
# ceiling, is the fastest this can go.
#
#   bash evals/night_shift.sh
#
# Resumable: every step checkpoints, so re-running skips finished work.
set -u
cd "$(dirname "$0")/.."
PY=backend/.venv/bin/python

# Groq meters tokens PER MODEL PER DAY (200k on the free tier), and the big
# model's day is already spent, so ask for the one that still has budget. The
# client would fall through to it anyway; naming it saves three wasted attempts
# on every call.
export GROQ_MODEL="${GROQ_MODEL:-openai/gpt-oss-20b}"
LOG=evals/corpus/night_shift.log

say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG"; }

say "=== night shift start ==="

# The tape goes FIRST. It is the CI gate, it is bounded at about 70k tokens,
# and the dataset can always be continued tomorrow while a half-recorded tape
# is worth nothing.
say "[1/4] recording the grounding eval tape (95 rows)"
$PY evals/run_evals.py --record --pause 3 >> "$LOG" 2>&1
say "[1/4] done: $(wc -l < evals/cassettes/grounding.jsonl 2>/dev/null || echo 0) recordings"

# Then the dataset, with its own token ceiling so the live site still has
# allowance in the morning. Resumable: tomorrow's run continues from here.
say "[2/4] building the labelled coverage dataset (token budget: ${BUILD_TOKEN_BUDGET:-90000})"
BUILD_TOKEN_BUDGET="${BUILD_TOKEN_BUDGET:-90000}" \
  $PY evals/build_coverage_dataset.py --pairs 1200 --test-size 150 --jds 45 --skip-harvest \
  >> "$LOG" 2>&1
say "[2/4] done: $(wc -l < evals/coverage_train.jsonl) training rows"

say "[3/4] training the coverage model"
$PY evals/train_coverage_model.py >> "$LOG" 2>&1
say "[3/4] done"

# The A/B is the most expensive step by far (two full tailoring runs, each six
# model calls, over twelve cases) and it is the least urgent. It runs only when
# explicitly asked for, so it cannot eat the allowance the site needs.
if [ "${RUN_PROMPT_AB:-0}" = "1" ]; then
  say "[4/4] A/B: tailoring prompt v1 against v2"
  $PY evals/run_prompt_ab.py --pause 20 >> "$LOG" 2>&1
  say "[4/4] done"
else
  say "[4/4] skipped the prompt A/B: it costs more tokens than a day's free"
  say "      allowance can spare. Run it with RUN_PROMPT_AB=1 when the budget resets."
fi

say "=== night shift finished ==="

# Added after the first human labelling pass: score the tightened grounding
# prompt against the same rows, so "v2 is better" is a number and not a hunch.
if [ "${RUN_GROUNDING_V2:-1}" = "1" ]; then
  say "[5/5] scoring grounding prompt v2 (specificity rule) against v1"
  $PY evals/run_evals.py --record --pause 3 --prompt-version v2 >> "$LOG" 2>&1
  say "[5/5] done"
fi
