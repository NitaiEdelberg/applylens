"""Build the labelled dataset for the learned coverage model.

The question every row answers: given this requirement and this CV, would a
careful person say the CV evidences it?

Where the data comes from, and why:

  jobs         real postings, fetched from LinkedIn's public guest endpoint,
               because a model trained on invented job descriptions learns the
               phrasing of invented job descriptions. Anything that cannot be
               fetched falls back to generated postings, and every row records
               which it was, so the split can be reported honestly.
  requirements the same extraction step the product runs, so the training
               distribution matches what the model will see in production.
  CVs          a pool of career profiles across domains and seniorities, so a
               requirement is judged against CVs that do and do not have it.
  labels       an LLM annotator at temperature 0, one requirement at a time
               inside a batch, asked for a reason as well as a verdict. Cheap
               enough to scale, noisy enough that the number quoted at the end
               must come from the human-labelled test set instead.

Everything is checkpointed: each stage appends to its own JSONL and re-running
skips work already done, so a run interrupted at 2am resumes rather than
restarts.

Usage:
    python evals/build_coverage_dataset.py --pairs 1200 --test-size 150
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

# A batch job wants different patience from a web request: nobody is waiting on
# a spinner, and the free tier's ceiling is per-minute tokens, so the right
# answer to a rate limit is to wait it out rather than fail the row. Set before
# importing the client, which reads these at import time.
os.environ.setdefault("LLM_MAX_ATTEMPTS", "6")
os.environ.setdefault("LLM_BACKOFF_SECONDS", "4")
os.environ.setdefault("LLM_TIMEOUT_SECONDS", "90")

from src import llm  # noqa: E402
from src.llm import LLMError, chat_json  # noqa: E402
from src.services.extract import extract_job  # noqa: E402
from src.services.skillmatch import skill_match  # noqa: E402

CORPUS = os.path.join(HERE, "corpus")
JDS_PATH = os.path.join(CORPUS, "jds.jsonl")
CVS_PATH = os.path.join(CORPUS, "cvs.json")
REQS_PATH = os.path.join(CORPUS, "requirements.jsonl")
LABELS_PATH = os.path.join(CORPUS, "labels.jsonl")
TRAIN_PATH = os.path.join(HERE, "coverage_train.jsonl")
TEST_PATH = os.path.join(HERE, "coverage_test_to_label.jsonl")
LOG_PATH = os.path.join(CORPUS, "build.log")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SEARCH_TERMS = [
    "AI Engineer", "Solutions Engineer", "Data Analyst", "Backend Developer",
    "Machine Learning Engineer", "DevOps Engineer", "Frontend Developer",
    "Analytics Engineer", "Platform Engineer", "Support Engineer",
]

# Ten personas plus the five already used by the deterministic eval. Written to
# span the axes that matter for coverage: domain, seniority, and how explicitly
# a CV names its tools.
PERSONA_BRIEFS = [
    "a junior backend developer, one year of experience, Java and Spring Boot, some Docker",
    "a senior data engineer, Airflow, dbt, Snowflake, Python, ten years of experience",
    "a frontend developer, five years, TypeScript, React, Next.js, design systems, accessibility",
    "a QA automation engineer, Playwright, Cypress, CI pipelines, some Python",
    "a technical support engineer moving into solutions engineering, SQL, Zendesk, customer calls",
    "an ML engineer, PyTorch, transformers, MLflow, feature stores, Kubernetes serving",
    "a mobile developer, Swift and Kotlin, no backend or cloud experience at all",
    "a product analyst, SQL, Looker, A/B testing, Python for analysis, stakeholder work",
    "a DevOps engineer, Terraform, AWS, Kubernetes, Go, on-call ownership",
    "a career-changer bootcamp graduate, JavaScript, Node, one deployed side project",
]

ANNOTATOR_SYSTEM = (
    "You are a careful annotator building a training set for a resume-screening "
    "model. For each requirement, decide whether the CV gives real evidence for "
    "it. Evidence means the CV states the skill, or states something that "
    "necessarily involves it (naming Snowflake is evidence for 'cloud data "
    "warehouse'). Adjacency is NOT evidence: working near a team that used "
    "Kubernetes is not Kubernetes experience, and a general category does not "
    "prove a specific named tool. Judge only skills and tools; a requirement "
    "about years of experience or seniority should be labelled uncertain. "
    "Respond with JSON only."
)

LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["covered", "missing", "uncertain"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "verdict"],
            },
        }
    },
    "required": ["labels"],
}


class Pacer:
    """Keeps the run under a tokens-per-minute ceiling.

    Groq's free tier allows 8,000 tokens a minute, and a labelling run will
    happily ask for ten times that. Retrying after each 429 works but wastes
    the whole minute; spacing the calls out in advance does not. Tokens are
    estimated at four characters each, which is close enough for pacing.
    """

    def __init__(self, tokens_per_minute=6500):
        self.budget = tokens_per_minute
        self.spent = []  # (timestamp, tokens)

    def _prune(self, now):
        self.spent = [entry for entry in self.spent if now - entry[0] < 60]

    async def reserve(self, estimated_tokens):
        while True:
            now = time.time()
            self._prune(now)
            used = sum(n for _, n in self.spent)
            if used + estimated_tokens <= self.budget or not self.spent:
                self.spent.append([now, estimated_tokens])
                return
            oldest = min(t for t, _ in self.spent)
            wait = max(1.0, 60 - (now - oldest))
            log("pacing: {} tokens used this minute, waiting {:.0f}s".format(used, wait))
            await asyncio.sleep(wait)

    def observed(self):
        return sum(n for _, n in self.spent)

    def settle(self):
        """Replace the last estimate with what the call actually cost.

        Character-count estimates under-count by a lot on a model that bills
        its own reasoning tokens, and an estimate that is half the real cost
        means every call gets rate limited and the run crawls.
        """
        usage = getattr(llm, "LAST_USAGE", None) or {}
        total = (usage.get("total_tokens")
                 or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
        if total and self.spent:
            self.spent[-1][1] = total
            self.last_actual = total


def estimate_tokens(*texts, expected_output=350):
    return sum(len(t or "") for t in texts) // 4 + expected_output


PACER = Pacer(int(os.getenv("BUILD_TPM_BUDGET", "3000")))


def log(message):
    line = "{} {}".format(time.strftime("%H:%M:%S"), message)
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_jsonl(path, row):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# stage 1: job descriptions
# --------------------------------------------------------------------------
def _strip_html(html):
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fetch(url, timeout=25):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8", "ignore")


def harvest_real_jds(target):
    """Real postings from LinkedIn's public guest endpoint, politely."""
    have = {row["id"] for row in read_jsonl(JDS_PATH)}
    found = 0
    for term in SEARCH_TERMS:
        if found >= target:
            break
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
               "?keywords={}&location=Israel&f_TPR=r2592000&start=0".format(
                   urllib.parse.quote(term)))
        try:
            html = _fetch(url)
        except Exception as exc:  # noqa: BLE001 — a blocked search is not fatal
            log("search failed for {}: {}".format(term, exc))
            time.sleep(2)
            continue

        ids = re.findall(r"jobPosting:(\d+)", html)
        for job_id in ids[:8]:
            if job_id in have or found >= target:
                continue
            try:
                page = _fetch("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
                              + job_id)
            except Exception as exc:  # noqa: BLE001
                log("posting {} failed: {}".format(job_id, exc))
                time.sleep(1.5)
                continue
            body = re.search(r'description__text[^>]*>(.*?)</div>\s*</div>', page, re.S)
            text = _strip_html(body.group(1)) if body else ""
            title = re.search(r'topcard__title[^>]*>\s*(.*?)\s*</h2>', page, re.S)
            if len(text) < 400:  # a stub, not a description
                time.sleep(0.8)
                continue
            append_jsonl(JDS_PATH, {
                "id": job_id,
                "title": _strip_html(title.group(1)) if title else term,
                "text": text[:6000],
                "source": "linkedin",
            })
            have.add(job_id)
            found += 1
            time.sleep(1.0)  # be a good guest
        time.sleep(1.0)
    log("harvested {} real postings".format(found))
    return found


JD_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
    "required": ["title", "text"],
}


async def generate_jds(count):
    """Fallback when the public endpoint will not talk to us."""
    made = 0
    for index in range(count):
        role = SEARCH_TERMS[index % len(SEARCH_TERMS)]
        await PACER.reserve(estimate_tokens(role, expected_output=600))
        try:
            data = await chat_json(
                [{"role": "system", "content": "You write realistic job postings. JSON only."},
                 {"role": "user", "content":
                  "Write one realistic job posting as json with keys title and text for a "
                  "{} role at a mid-size tech company. The text must read like a real "
                  "posting: responsibilities, then 6-9 requirements mixing named tools with "
                  "vaguer asks, then nice-to-haves. 200-350 words. Vary the seniority and "
                  "the industry from a typical posting.".format(role)}],
                temperature=0.9, schema=JD_SCHEMA)
            PACER.settle()
        except LLMError as exc:
            log("generation failed: {}".format(exc))
            continue
        append_jsonl(JDS_PATH, {
            "id": "gen-{}".format(index),
            "title": data.get("title", role),
            "text": data.get("text", ""),
            "source": "generated",
        })
        made += 1
    log("generated {} postings".format(made))
    return made


# --------------------------------------------------------------------------
# stage 2: CV pool
# --------------------------------------------------------------------------
CV_SCHEMA = {
    "type": "object",
    "properties": {"cv": {"type": "string"}},
    "required": ["cv"],
}


async def build_cv_pool():
    if os.path.exists(CVS_PATH):
        return json.load(open(CVS_PATH, encoding="utf-8"))

    # Start from the five CVs the deterministic eval already uses, so the two
    # datasets share a vocabulary.
    pool = dict(json.load(open(os.path.join(HERE, "skillmatch_cvs.json"), encoding="utf-8")))
    for index, brief in enumerate(PERSONA_BRIEFS):
        await PACER.reserve(estimate_tokens(brief, expected_output=450))
        try:
            data = await chat_json(
                [{"role": "system", "content": "You write realistic CV summaries. JSON only."},
                 {"role": "user", "content":
                  "Write the experience section of a real CV as json with key cv, for {}. "
                  "150-220 words, first person omitted, concrete tools and outcomes, no "
                  "headings, no invented awards. Name the tools the way a real CV does: "
                  "some explicitly, some only implied by what was built.".format(brief)}],
                temperature=0.8, schema=CV_SCHEMA)
            PACER.settle()
        except LLMError as exc:
            log("cv generation failed: {}".format(exc))
            continue
        pool["persona{}".format(index)] = data.get("cv", "")
    os.makedirs(CORPUS, exist_ok=True)
    json.dump(pool, open(CVS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log("cv pool: {} CVs".format(len(pool)))
    return pool


# --------------------------------------------------------------------------
# stage 3: requirements
# --------------------------------------------------------------------------
async def extract_requirements(jds):
    done = {row["jd_id"] for row in read_jsonl(REQS_PATH)}
    for jd in jds:
        if jd["id"] in done:
            continue
        await PACER.reserve(estimate_tokens(jd["text"], expected_output=300))
        try:
            job = await extract_job(jd["text"])
            PACER.settle()
        except LLMError as exc:
            log("extract failed for {}: {}".format(jd["id"], exc))
            continue
        requirements = [r for r in (list(job.get("must_haves", []))
                                    + list(job.get("nice_to_haves", []))) if r and r.strip()]
        append_jsonl(REQS_PATH, {
            "jd_id": jd["id"], "title": job.get("title", jd.get("title", "")),
            "source": jd.get("source", "unknown"), "requirements": requirements[:12],
        })
        log("extracted {} requirements from {}".format(len(requirements), jd["id"]))
    return read_jsonl(REQS_PATH)


# --------------------------------------------------------------------------
# stage 4: pair and label
# --------------------------------------------------------------------------
def build_pairs(requirement_rows, cvs, target, cvs_per_requirement, seed=17):
    rng = random.Random(seed)
    cv_keys = sorted(cvs)
    pairs = []
    for row in requirement_rows:
        for requirement in row["requirements"]:
            for cv_key in rng.sample(cv_keys, min(cvs_per_requirement, len(cv_keys))):
                pairs.append({
                    "pair_id": "{}::{}::{}".format(row["jd_id"], cv_key,
                                                   re.sub(r"\W+", "_", requirement.lower())[:40]),
                    "jd_id": row["jd_id"], "jd_source": row["source"],
                    "cv_key": cv_key, "requirement": requirement,
                })
    rng.shuffle(pairs)
    return pairs[:target]


async def label_batch(cv_text, items):
    """One call labels several requirements against one CV."""
    listed = "\n".join("{}. {}".format(i, item["requirement"]) for i, item in enumerate(items))
    await PACER.reserve(estimate_tokens(cv_text, listed, ANNOTATOR_SYSTEM,
                                        expected_output=90 * len(items)))
    data = await chat_json(
        [{"role": "system", "content": ANNOTATOR_SYSTEM},
         {"role": "user", "content":
          'Return json with key "labels": one entry per requirement, each with index, '
          'verdict (covered, missing, or uncertain) and a reason of AT MOST 10 words. '
          "Be brief; the verdict matters more than the prose.\n\nCV:\n\"\"\"{}\"\"\""
          "\n\nREQUIREMENTS:\n{}".format(
              cv_text, listed)}],
        temperature=0.0, schema=LABEL_SCHEMA)
    PACER.settle()
    # The schema is not strictly enforced by every model, so this has seen
    # `labels` come back as a list of bare strings. One malformed batch must
    # cost that batch, not the whole run.
    out = {}
    raw = data.get("labels")
    if isinstance(raw, dict):
        raw = list(raw.values())
    for position, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        index = entry.get("index", position)
        if isinstance(index, int) and 0 <= index < len(items):
            out[index] = entry
    return out


async def label_pairs(pairs, cvs, batch_size=8, pause=0.2):
    done = {row["pair_id"] for row in read_jsonl(LABELS_PATH)}
    todo = [p for p in pairs if p["pair_id"] not in done]
    log("labelling {} pairs ({} already done)".format(len(todo), len(done)))

    by_cv = {}
    for pair in todo:
        by_cv.setdefault(pair["cv_key"], []).append(pair)

    labelled = 0
    for cv_key, items in by_cv.items():
        cv_text = cvs[cv_key]
        for start in range(0, len(items), batch_size):
            batch = items[start:start + batch_size]
            try:
                verdicts = await label_batch(cv_text, batch)
            except LLMError as exc:
                log("label batch failed ({}): {}".format(cv_key, exc))
                await asyncio.sleep(5)
                continue
            except Exception as exc:  # noqa: BLE001 — one bad batch, not the run
                log("label batch unusable ({}): {}: {}".format(
                    cv_key, type(exc).__name__, exc))
                continue
            for index, pair in enumerate(batch):
                entry = verdicts.get(index)
                if not entry:
                    continue
                rule = bool(skill_match([pair["requirement"]], cv_text)["covered"])
                append_jsonl(LABELS_PATH, dict(
                    pair,
                    verdict=entry.get("verdict"),
                    reason=(entry.get("reason") or "")[:300],
                    rule_says_covered=rule,
                ))
                labelled += 1
            if labelled and labelled % 40 == 0:
                log("labelled {} (last call {} tokens, {} in the last minute)".format(
                    labelled, getattr(PACER, "last_actual", "?"), PACER.observed()))
            await asyncio.sleep(pause)
    log("labelled {} new pairs".format(labelled))


# --------------------------------------------------------------------------
# stage 5: split
# --------------------------------------------------------------------------
def write_splits(test_size, seed=17):
    """Split by CV, never by row: the test set must be CVs the model never saw.

    The test file is deliberately unlabelled. Its verdicts are for a human to
    fill in, because a number measured against the annotator's own labels only
    proves the model learned to imitate the annotator.
    """
    rows = read_jsonl(LABELS_PATH)
    usable = [r for r in rows if r.get("verdict") in ("covered", "missing")]
    uncertain = len(rows) - len(usable)

    cv_keys = sorted({r["cv_key"] for r in usable})
    rng = random.Random(seed)
    rng.shuffle(cv_keys)
    holdout = set(cv_keys[:max(2, len(cv_keys) // 4)])

    train = [r for r in usable if r["cv_key"] not in holdout]
    pool = [r for r in usable if r["cv_key"] in holdout]

    # Over-sample the rows where the rule and the annotator disagree: those are
    # the ones that decide whether the model is worth shipping, and a test set
    # of easy agreements would say nothing.
    disagree = [r for r in pool if r["rule_says_covered"] != (r["verdict"] == "covered")]
    agree = [r for r in pool if r["rule_says_covered"] == (r["verdict"] == "covered")]
    rng.shuffle(disagree)
    rng.shuffle(agree)
    take_disagree = min(len(disagree), test_size // 2)
    test = disagree[:take_disagree] + agree[:test_size - take_disagree]
    rng.shuffle(test)

    with open(TRAIN_PATH, "w", encoding="utf-8") as handle:
        for row in train:
            handle.write(json.dumps(dict(row, label=row["verdict"] == "covered"),
                                    ensure_ascii=False) + "\n")
    with open(TEST_PATH, "w", encoding="utf-8") as handle:
        for row in test:
            handle.write(json.dumps({
                "pair_id": row["pair_id"], "cv_key": row["cv_key"],
                "requirement": row["requirement"], "jd_source": row["jd_source"],
                # kept for later comparison, and NOT to be shown while labelling
                "annotator_verdict": row["verdict"], "rule_says_covered": row["rule_says_covered"],
                "human_label": None,
            }, ensure_ascii=False) + "\n")

    log("train {} rows over {} CVs | test {} rows over {} held-out CVs "
        "({} of them rule/annotator disagreements) | {} uncertain rows dropped".format(
            len(train), len(cv_keys) - len(holdout), len(test), len(holdout),
            take_disagree, uncertain))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=1200)
    parser.add_argument("--test-size", type=int, default=150)
    parser.add_argument("--jds", type=int, default=45)
    parser.add_argument("--cvs-per-requirement", type=int, default=3)
    parser.add_argument("--skip-harvest", action="store_true")
    args = parser.parse_args()

    os.makedirs(CORPUS, exist_ok=True)
    log("=== build start: target {} pairs ===".format(args.pairs))

    existing = read_jsonl(JDS_PATH)
    if not args.skip_harvest and len(existing) < args.jds:
        harvest_real_jds(args.jds - len(existing))
    existing = read_jsonl(JDS_PATH)
    if len(existing) < args.jds:
        # Honest fallback: the run still produces a dataset, and every row says
        # whether its posting was real or generated.
        await generate_jds(args.jds - len(existing))
    jds = read_jsonl(JDS_PATH)
    real = sum(1 for j in jds if j["source"] == "linkedin")
    log("{} postings ({} real, {} generated)".format(len(jds), real, len(jds) - real))

    cvs = await build_cv_pool()
    requirement_rows = await extract_requirements(jds)
    pairs = build_pairs(requirement_rows, cvs, args.pairs, args.cvs_per_requirement)
    log("{} pairs to label".format(len(pairs)))
    await label_pairs(pairs, cvs)
    write_splits(args.test_size)
    log("=== build done ===")


if __name__ == "__main__":
    asyncio.run(main())
