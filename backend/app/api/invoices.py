"""Extracted invoices: list, detail, corrections, review, export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import services
from ..db import get_db
from ..models import Correction, Invoice, ValidationIssue
from ..schemas import CorrectionOut, CorrectionRequest, InvoiceBrief, InvoiceDetail, ReviewRequest

router = APIRouter(prefix="/invoices", tags=["invoices"])


def filters(q, supplier=None, customer=None, invoice_number=None, currency=None, date_from=None, date_to=None,
            min_total=None, max_total=None, review_status=None, issue_code=None, document_id=None):
    if supplier:
        q = q.where(Invoice.supplier_name.ilike(f"%{supplier}%"))
    if customer:
        q = q.where(Invoice.customer_name.ilike(f"%{customer}%"))
    if invoice_number:
        q = q.where(Invoice.invoice_number.ilike(f"%{invoice_number}%"))
    if currency:
        q = q.where(Invoice.currency == currency.upper())
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    if min_total is not None:
        q = q.where(Invoice.total >= min_total)
    if max_total is not None:
        q = q.where(Invoice.total <= max_total)
    if review_status:
        q = q.where(Invoice.review_status == review_status)
    if issue_code:
        q = q.where(Invoice.id.in_(select(ValidationIssue.invoice_id).where(
            ValidationIssue.code == issue_code, ValidationIssue.resolved.is_(False))))
    if document_id:
        q = q.where(Invoice.document_id == document_id)
    return q


class Filters:
    def __init__(self, supplier: str | None = None, customer: str | None = None, invoice_number: str | None = None,
                 currency: str | None = None, date_from: date | None = None, date_to: date | None = None,
                 min_total: Decimal | None = None, max_total: Decimal | None = None,
                 review_status: str | None = None, issue_code: str | None = None,
                 document_id: uuid.UUID | None = None):
        self.kw = dict(supplier=supplier, customer=customer, invoice_number=invoice_number, currency=currency,
                       date_from=date_from, date_to=date_to, min_total=min_total, max_total=max_total,
                       review_status=review_status, issue_code=issue_code, document_id=document_id)

    def apply(self, q):
        return filters(q, **self.kw)


def not_found():
    return HTTPException(404, detail={"code": "not_found", "message": "Invoice not found"})


@router.get("")
def list_invoices(f: Filters = Depends(), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db)):
    q = f.apply(select(Invoice))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = list(db.scalars(q.order_by(Invoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    counts = dict(db.execute(select(ValidationIssue.invoice_id, func.count())
                             .where(ValidationIssue.invoice_id.in_([r.id for r in rows]),
                                    ValidationIssue.resolved.is_(False))
                             .group_by(ValidationIssue.invoice_id)).all()) if rows else {}
    items = []
    for r in rows:
        b = InvoiceBrief.model_validate(r)
        b.issue_count = counts.get(r.id, 0)
        items.append(b.model_dump(mode="json"))
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/export")
def export(f: Filters = Depends(), format: str = Query("csv", pattern="^(csv|json)$"), db: Session = Depends(get_db)):
    rows = list(db.scalars(f.apply(select(Invoice)).options(selectinload(Invoice.line_items))
                           .order_by(Invoice.invoice_date)))
    if format == "json":
        return [_detail(r).model_dump(mode="json", exclude={"issues", "evidence", "field_confidence"}) for r in rows]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["invoice_id", "document_id", "invoice_number", "invoice_date", "supplier_name", "customer_name",
                "subtotal", "tax", "total", "currency", "line_count", "review_status", "extraction_method"])
    for r in rows:
        w.writerow([r.id, r.document_id, r.invoice_number, r.invoice_date, r.supplier_name, r.customer_name,
                    r.subtotal, r.tax, r.total, r.currency, len(r.line_items), r.review_status, r.extraction_method])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=invoices.csv"})


def _load(db: Session, inv_id) -> Invoice:
    inv = db.scalar(select(Invoice).where(Invoice.id == inv_id).options(
        selectinload(Invoice.line_items), selectinload(Invoice.issues), selectinload(Invoice.group),
        selectinload(Invoice.document)))
    if not inv:
        raise not_found()
    return inv


def _detail(inv: Invoice) -> InvoiceDetail:
    d = InvoiceDetail.model_validate(inv)
    d.issues = [i for i in d.issues if not i.resolved] + [i for i in d.issues if i.resolved]
    d.evidence = {k: v for k, v in (inv.evidence or {}).items() if not k.startswith("_")}
    d.document_filename = inv.document.original_filename if inv.document else None
    return d


@router.get("/{inv_id}", response_model=InvoiceDetail)
def get_invoice(inv_id: uuid.UUID, db: Session = Depends(get_db)):
    return _detail(_load(db, inv_id))


@router.patch("/{inv_id}", response_model=InvoiceDetail)
def correct(inv_id: uuid.UUID, body: CorrectionRequest, db: Session = Depends(get_db)):
    inv = _load(db, inv_id)
    fields = body.fields.model_dump(exclude_unset=True)
    if "currency" in fields and fields["currency"]:
        fields["currency"] = fields["currency"].upper()
    lines = [li.model_dump() for li in body.line_items] if body.line_items is not None else None
    if not fields and lines is None:
        raise HTTPException(400, detail={"code": "nothing_to_change", "message": "No fields or line items given"})
    services.apply_correction(db, inv, fields, lines, body.corrected_by, body.note)
    db.commit()
    db.expire_all()
    return _detail(_load(db, inv_id))


@router.post("/{inv_id}/review", response_model=InvoiceDetail)
def review(inv_id: uuid.UUID, body: ReviewRequest, db: Session = Depends(get_db)):
    inv = _load(db, inv_id)
    blocking = [i for i in inv.issues if i.severity == "error" and not i.resolved]
    if blocking and body.decision == "approve":
        raise HTTPException(409, detail={"code": "unresolved_errors",
                                         "message": f"{len(blocking)} error(s) must be corrected before approval",
                                         "details": {"issues": [i.message for i in blocking]}})
    for i in inv.issues:
        if not i.resolved:
            i.resolved = True
            i.details = {**(i.details or {}), "resolved_by": body.reviewed_by, "decision": body.decision,
                         "note": body.note}
    inv.review_status = "reviewed"
    inv.reviewed_by, inv.reviewed_at = body.reviewed_by, services.now()
    db.flush()
    others = db.scalars(select(Invoice.review_status).where(Invoice.document_id == inv.document_id)).all()
    inv.document.status = "needs_review" if "needs_review" in others else "completed"
    db.commit()
    db.expire_all()
    return _detail(_load(db, inv_id))


@router.get("/{inv_id}/corrections", response_model=list[CorrectionOut])
def corrections(inv_id: uuid.UUID, db: Session = Depends(get_db)):
    if not db.get(Invoice, inv_id):
        raise not_found()
    return list(db.scalars(select(Correction).where(Correction.invoice_id == inv_id).order_by(Correction.created_at)))
