"""Request/response models for the ApplyLens API."""
from typing import Any, List, Optional
from pydantic import BaseModel


# ---- requests ----
class ExtractRequest(BaseModel):
    jd_text: str


class AnalyzeRequest(BaseModel):
    jd_text: str
    cv_text: str
    # Optional longer career history (multiple roles/projects). When present,
    # RAG retrieves the most relevant pieces per job and adds them as an extra
    # GROUNDED source for tailoring. Absent → behaves exactly as before.
    career_text: Optional[str] = None


# ---- extraction ----
class ExtractedJob(BaseModel):
    title: str = ""
    seniority: str = ""
    must_haves: List[str] = []
    nice_to_haves: List[str] = []
    stack: List[str] = []


# ---- fit scoring ----
class MatchedReq(BaseModel):
    requirement: str
    evidence: str


class PartialReq(BaseModel):
    requirement: str
    note: str


class FitResult(BaseModel):
    overall_score: int = 0
    matched: List[MatchedReq] = []
    partial: List[PartialReq] = []
    missing: List[str] = []
    summary: str = ""


# ---- tailoring + grounding guardrail ----
class GroundingCheck(BaseModel):
    statement: str
    supported: bool
    evidence: Optional[str] = None
    issue: Optional[str] = None


class TailorResult(BaseModel):
    bullets: List[str] = []
    cover_letter: str = ""
    grounding: List[GroundingCheck] = []
    flagged_count: int = 0
    # Cover-letter guardrail: grounding verdicts for ONLY the letter's extracted
    # factual self-claims (GroundingCheck.statement holds the claim text).
    cover_grounding: List[GroundingCheck] = []
    cover_flagged_count: int = 0


# ---- self-correcting "Fix this bullet" loop ----
class RegenerateBulletRequest(BaseModel):
    jd_text: str
    cv_text: str
    bullet: str
    issue: str = ""


class RegenerateBulletResponse(BaseModel):
    bullet: str
    grounding: GroundingCheck


# ---- deterministic (non-LLM) skill-coverage signal ----
class MatchedTerm(BaseModel):
    """Which requirement term was covered, and the CV word that covered it."""
    term: str
    evidence: str


class CoveredReq(BaseModel):
    requirement: str
    score: float = 0.0
    matched: List[MatchedTerm] = []


class MissingReq(BaseModel):
    requirement: str
    unmatched: List[str] = []


class SkillMatch(BaseModel):
    coverage_score: int = 0
    covered: List[CoveredReq] = []
    # Plain requirement strings: what the UI renders. The per-term reasons ride
    # in missing_detail so the wire shape stays what older clients expect.
    missing: List[str] = []
    missing_detail: List[MissingReq] = []
    method: str = "term coverage"


# ---- per-request trace ----
class LLMCall(BaseModel):
    model: str
    ms: int = 0
    status: int = 200
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    retried: bool = False


class TraceStage(BaseModel):
    name: str
    ms: int = 0
    calls: List[LLMCall] = []
    error: Optional[str] = None


class TraceTotals(BaseModel):
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Only present when real per-token prices are configured; a guessed cost is
    # worse than no cost.
    cost_usd: Optional[float] = None
    models: List[str] = []


class RequestTrace(BaseModel):
    request_id: str
    name: str = ""
    total_ms: int = 0
    stages: List[TraceStage] = []
    totals: TraceTotals = TraceTotals()
    # True when the answer came from the in-process cache rather than the model.
    cached: bool = False


# ---- RAG over the optional career-history corpus (Circle 4) ----
class RagInfo(BaseModel):
    used: bool = False
    # The career-history chunks retrieved for this job (grounded source, shown
    # to the user). Empty when RAG wasn't used.
    chunks: List[str] = []
    # Which embedder produced the retrieval: "gemini" (hosted) or "tfidf" (local).
    source: str = "tfidf"


# ---- combined one-call analyze ----
class AnalyzeResponse(BaseModel):
    job: ExtractedJob
    fit: FitResult
    tailor: TailorResult
    # Deterministic TF-IDF keyword-coverage second opinion (no LLM call).
    skill_match: SkillMatch = SkillMatch()
    # RAG retrieval over the optional career corpus. used=false when no
    # career_text was supplied (behavior identical to before).
    rag: RagInfo = RagInfo()
    # What actually happened inside this request: stages, latency, tokens, and
    # the model that answered. Empty on responses produced before tracing.
    trace: Optional[RequestTrace] = None


# ---- optional accounts (Circle 3) ----
class AuthRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    token: str
    email: str


# ---- per-user cloud tracker ----
class TrackerCreate(BaseModel):
    title: str = "Untitled role"
    company: str = ""
    status: str = "applied"
    score: Optional[int] = None
    flagged: int = 0
    # The full saved analysis blob (same shape the localStorage tracker keeps).
    payload: Optional[Any] = None


class TrackerStatusUpdate(BaseModel):
    status: str


class TrackedApp(BaseModel):
    id: int
    title: str
    company: str
    status: str
    score: Optional[int] = None
    flagged: int = 0
    payload: Optional[Any] = None
    savedAt: Optional[str] = None
