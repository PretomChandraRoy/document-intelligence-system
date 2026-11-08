"""Keyword, semantic and hybrid search over extracted invoices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Invoice
from ..pipeline.llm import get_client
from ..schemas import SearchHit, SearchResponse
from ..security import limiter
from .invoices import Filters

router = APIRouter(tags=["search"])
RRF_K = 60  # standard constant for reciprocal rank fusion


@router.get("/search", response_model=SearchResponse)
@limiter.limit(lambda: get_settings().rate_limit_search)
def search(request: Request, q: str | None = Query(None, max_length=500),
           mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
           limit: int = Query(20, ge=1, le=100), f: Filters = Depends(), db: Session = Depends(get_db)):
    base = f.apply(select(Invoice))
    if not q or not q.strip():
        rows = list(db.scalars(base.order_by(Invoice.invoice_date.desc().nullslast()).limit(limit)))
        return SearchResponse(mode=mode, query=q, results=[_hit(r, 0.0, None, None, None) for r in rows])

    keyword: list[tuple] = []
    semantic: list[tuple] = []
    if mode in ("keyword", "hybrid"):
        tsq = func.websearch_to_tsquery("simple", q)
        rank = func.ts_rank(Invoice.search_tsv, tsq).label("rank")
        sub = base.subquery()
        rows = db.execute(select(Invoice, rank).join(sub, sub.c.id == Invoice.id)
                          .where(Invoice.search_tsv.op("@@")(tsq)).order_by(rank.desc()).limit(limit * 3)).all()
        # also match partial names and numbers that full-text search splits differently
        if not rows:
            like = f"%{q.strip()}%"
            rows = [(r, 0.01) for r in db.scalars(base.where(
                Invoice.supplier_name.ilike(like) | Invoice.customer_name.ilike(like) |
                Invoice.invoice_number.ilike(like)).limit(limit * 3))]
        keyword = [(r, float(s)) for r, s in rows]
    if mode in ("semantic", "hybrid"):
        try:
            client = get_client()
            vec = client.embed([q])[0]
            dist = Invoice.embedding.cosine_distance(vec).label("dist")
            sub = base.subquery()
            rows = db.execute(select(Invoice, dist).join(sub, sub.c.id == Invoice.id)
                              .where(Invoice.embedding.is_not(None)).order_by(dist).limit(limit * 3)).all()
            floor = getattr(client, "min_similarity", get_settings().semantic_min_similarity)
            semantic = [(r, 1 - float(d)) for r, d in rows if 1 - float(d) >= floor]
        except Exception:
            semantic = []  # model unavailable: keyword results still returned

    scores: dict = {}
    for ranklist, key in ((keyword, "k"), (semantic, "s")):
        for pos, (inv, _) in enumerate(ranklist, start=1):
            e = scores.setdefault(inv.id, {"inv": inv, "score": 0.0, "k": None, "s": None})
            e["score"] += 1.0 / (RRF_K + pos)
            e[key] = pos
    ranked = sorted(scores.values(), key=lambda e: -e["score"])[:limit]
    snippets = _snippets(db, q, [e["inv"].id for e in ranked]) if keyword else {}
    return SearchResponse(mode=mode, query=q, results=[
        _hit(e["inv"], round(e["score"], 5), e["k"], e["s"], snippets.get(e["inv"].id)) for e in ranked])


def _snippets(db: Session, q: str, ids) -> dict:
    if not ids:
        return {}
    tsq = func.websearch_to_tsquery("simple", q)
    rows = db.execute(select(Invoice.id, func.ts_headline(
        "simple", Invoice.search_text, tsq,
        literal_column("'MaxFragments=1,MaxWords=18,MinWords=6,StartSel=<b>,StopSel=</b>'")))
        .where(Invoice.id.in_(ids))).all()
    return dict(rows)


def _hit(inv: Invoice, score, k, s, snippet) -> SearchHit:
    return SearchHit(invoice_id=inv.id, document_id=inv.document_id, invoice_number=inv.invoice_number,
                     supplier_name=inv.supplier_name, customer_name=inv.customer_name,
                     invoice_date=inv.invoice_date, total=inv.total, currency=inv.currency,
                     review_status=inv.review_status, score=score, keyword_rank=k, semantic_rank=s,
                     snippet=snippet)
