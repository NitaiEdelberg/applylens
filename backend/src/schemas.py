"""Request/response models for the ApplyLens API."""
from typing import List, Optional
from pydantic import BaseModel


# ---- requests ----
class ExtractRequest(BaseModel):
    jd_text: str


class AnalyzeRequest(BaseModel):
    jd_text: str
    cv_text: str


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
