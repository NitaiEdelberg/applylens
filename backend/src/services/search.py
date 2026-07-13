"""Elasticsearch-powered full-text search over a user's tracked applications
(Circle 5), with a graceful DB fallback so the feature is fully testable with NO
Elasticsearch instance.

Deliberately built on plain ``httpx`` against the ES REST API rather than the
version-coupled ``elasticsearch`` Python client: Bonsai/Elastic Cloud hand you a
single URL with credentials embedded (``https://USER:PASS@host``), which httpx
consumes directly, and httpx is already a dependency (no new heavy dep, no
client/server version pinning).

Two invariants:
  * ES is an *index*, never the source of truth — Postgres/SQLite still owns the
    data. Every write here is best-effort and MUST NOT raise (ES being down can
    never break saving a tracked application).
  * ``search_apps`` raises :class:`SearchUnavailable` on any ES error so the
    caller falls back to a DB substring query, keeping search always-available.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from ..config import ELASTICSEARCH_INDEX, ELASTICSEARCH_URL

logger = logging.getLogger(__name__)

# Short timeout: a slow/unreachable ES must degrade to the DB fallback quickly,
# not stall the request. Bonsai on a warm connection answers in tens of ms.
_TIMEOUT = 5.0

# Cache the "does the index exist" check so we don't PUT a mapping on every
# write. Reset implicitly per-process; ES's create-if-missing is idempotent
# anyway (a 400 "resource_already_exists_exception" is treated as success).
_index_ready = False


class SearchUnavailable(Exception):
    """Sentinel raised by :func:`search_apps` when ES is disabled or errors, so
    the endpoint knows to fall back to the DB substring query."""


def es_enabled() -> bool:
    """True when an Elasticsearch URL is configured (ELASTICSEARCH_URL/BONSAI_URL)."""
    return bool(ELASTICSEARCH_URL)


def _base_url() -> str:
    return ELASTICSEARCH_URL.rstrip("/")


def _doc_text(app) -> str:
    """Concatenate the searchable free text for an app: title + company + the
    saved analysis payload's extracted job title / requirements. Best-effort —
    a missing or malformed payload just contributes nothing."""
    parts: List[str] = [app.title or "", app.company or ""]
    payload = getattr(app, "payload", None)
    if isinstance(payload, str):
        # The tracked-application row stores payload as a JSON string.
        import json

        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = None
    if isinstance(payload, dict):
        job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
        if isinstance(job, dict):
            parts.append(str(job.get("title", "")))
            for key in ("must_haves", "nice_to_haves", "stack"):
                vals = job.get(key)
                if isinstance(vals, (list, tuple)):
                    parts.extend(str(v) for v in vals)
    return " ".join(p for p in parts if p).strip()


def _ensure_index() -> None:
    """Create the index with a simple mapping if it doesn't exist. Best-effort
    and idempotent; raises only on an unexpected HTTP error so callers that must
    not fail (``index_app``) can swallow it."""
    global _index_ready
    if _index_ready:
        return
    url = f"{_base_url()}/{ELASTICSEARCH_INDEX}"
    mapping = {
        "mappings": {
            "properties": {
                "user_id": {"type": "keyword"},
                "title": {"type": "text"},
                "company": {"type": "text"},
                "status": {"type": "keyword"},
                "text": {"type": "text"},
            }
        }
    }
    resp = httpx.put(url, json=mapping, timeout=_TIMEOUT)
    # 200 = created; 400 resource_already_exists = fine; anything else is an error.
    if resp.status_code == 400 and "resource_already_exists" in resp.text:
        _index_ready = True
        return
    resp.raise_for_status()
    _index_ready = True


def index_app(app) -> None:
    """Best-effort: PUT the tracked application as a document (id = app id).

    NEVER raises — ES being unreachable must not break saving a tracked app.
    On any failure it logs a warning and returns. Call this after create and on
    status change (fire-and-forget)."""
    if not es_enabled():
        return
    try:
        _ensure_index()
        doc = {
            "user_id": str(app.user_id),
            "title": app.title or "",
            "company": app.company or "",
            "status": app.status or "",
            "text": _doc_text(app),
        }
        url = f"{_base_url()}/{ELASTICSEARCH_INDEX}/_doc/{app.id}"
        resp = httpx.put(url, json=doc, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — indexing is best-effort, never fatal
        logger.warning("Elasticsearch index_app failed for app %s: %s", getattr(app, "id", "?"), exc)


def delete_app(app_id) -> None:
    """Best-effort: remove a document from the index. Never raises (a 404 for an
    already-absent doc is fine)."""
    if not es_enabled():
        return
    try:
        url = f"{_base_url()}/{ELASTICSEARCH_INDEX}/_doc/{app_id}"
        httpx.delete(url, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — deletion from the index is non-fatal
        logger.warning("Elasticsearch delete_app failed for app %s: %s", app_id, exc)


def search_apps(user_id, q: str, size: int = 25) -> List[int]:
    """Search a user's applications by free text, returning ordered app ids.

    POSTs a ``_search`` with a bool query: ``must`` multi_match of ``q`` over
    title/company/text and a ``filter`` term on ``user_id`` (so a user can only
    ever match their own docs). Returns the relevance-ordered list of app ids.

    Raises :class:`SearchUnavailable` when ES is disabled or on ANY error, so the
    caller falls back to the DB substring query."""
    if not es_enabled():
        raise SearchUnavailable("Elasticsearch is not configured")
    try:
        _ensure_index()
        body = {
            "size": size,
            "_source": False,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": q,
                                "fields": ["title^2", "company^2", "text"],
                            }
                        }
                    ],
                    "filter": [{"term": {"user_id": str(user_id)}}],
                }
            },
        }
        url = f"{_base_url()}/{ELASTICSEARCH_INDEX}/_search"
        resp = httpx.post(url, json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        ids: List[int] = []
        for h in hits:
            hid = h.get("_id")
            if hid is None:
                continue
            try:
                ids.append(int(hid))
            except (ValueError, TypeError):
                continue
        return ids
    except SearchUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — any ES failure => fall back to the DB
        logger.warning("Elasticsearch search_apps failed: %s", exc)
        raise SearchUnavailable(str(exc)) from exc
