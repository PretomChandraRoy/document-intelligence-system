"""Health check and statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Document, Invoice, Page

router = APIRouter(tags=["system"])
VERSION = "1.0.0"


def health_payload(db: Session) -> dict:
    out = {"database": "ok", "redis": "ok", "llm": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        out["database"] = "down"
    try:
        import redis
        redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2).ping()
    except Exception:
        out["redis"] = "down"
    try:
        from ..pipeline.llm import get_client
        out["llm"] = "ok" if get_client().health() else "down"
    except Exception:
        out["llm"] = "down"
    out["status"] = "ok" if all(v == "ok" for v in out.values()) else "degraded"
    out["version"] = VERSION
    out["llm_provider"] = get_settings().llm_provider
    return out


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    docs = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    invs = dict(db.execute(select(Invoice.review_status, func.count()).group_by(Invoice.review_status)).all())
    methods = dict(db.execute(select(Invoice.extraction_method, func.count()).group_by(Invoice.extraction_method)).all())
    errors = dict(db.execute(select(Document.error_code, func.count()).where(Document.status == "failed")
                             .group_by(Document.error_code)).all())
    per_page = dict(db.execute(select(Page.kind, func.avg(Page.processing_ms)).where(Page.processing_ms.is_not(None))
                               .group_by(Page.kind)).all())
    return {
        "documents": {"total": sum(docs.values()), **{k: docs.get(k, 0) for k in
                      ("queued", "processing", "completed", "needs_review", "failed")}},
        "failure_reasons": errors,
        "invoices": {"total": sum(invs.values()), **{k: invs.get(k, 0) for k in
                     ("auto_approved", "needs_review", "reviewed")}},
        "extraction_method": methods,
        "avg_ocr_ms_per_page": {k: round(float(v)) for k, v in per_page.items()},
    }
