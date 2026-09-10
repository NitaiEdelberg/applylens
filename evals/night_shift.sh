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

say "[1/4] building the labelled coverage dataset"
$PY evals/build_coverage_dataset.py --pairs 1200 --test-size 150 --jds 45 --skip-harvest \
  >> "$LOG" 2>&1
say "[1/4] done: $(wc -l < evals/coverage_train.jsonl) training rows"

say "[2/4] recording the grounding eval tape (95 rows)"
$PY evals/run_evals.py --record --pause 3 >> "$LOG" 2>&1
say "[2/4] done: $(wc -l < evals/cassettes/grounding.jsonl 2>/dev/null || echo 0) recordings"

say "[3/4] training the coverage model"
$PY evals/train_coverage_model.py >> "$LOG" 2>&1
say "[3/4] done"

say "[4/4] A/B: tailoring prompt v1 against v2"
$PY evals/run_prompt_ab.py --pause 20 >> "$LOG" 2>&1
say "[4/4] done"

say "=== night shift finished ==="
