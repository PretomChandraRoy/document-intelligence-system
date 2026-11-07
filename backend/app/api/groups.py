"""Duplicates and cross-verification."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import services
from ..db import get_db
from ..models import Invoice, InvoiceGroup
from ..pipeline.matching import compare
from ..schemas import CrossVerifyRequest, CrossVerifyResponse, GroupDetail, GroupMember

router = APIRouter(tags=["cross-verification"])


def _members(db: Session, group_id) -> list[Invoice]:
    return list(db.scalars(select(Invoice).where(Invoice.group_id == group_id)
                           .options(selectinload(Invoice.line_items), selectinload(Invoice.document))
                           .order_by(Invoice.created_at)))


def _detail(db: Session, g: InvoiceGroup) -> GroupDetail:
    members = _members(db, g.id)
    _, rows = compare(members) if len(members) > 1 else ([], [])
    return GroupDetail(id=g.id, status=g.status, match_method=g.match_method, match_key=g.match_key,
                       mismatched_fields=g.mismatched_fields or [],
                       members=[GroupMember(invoice_id=m.id, document_id=m.document_id,
                                            document=m.document.original_filename, format=m.document.format)
                                for m in members],
                       comparison=rows)


@router.get("/groups")
def list_groups(status: str | None = Query(None, pattern="^(consistent|mismatch)$"),
                match_method: str | None = None, page: int = Query(1, ge=1),
                page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    q = select(InvoiceGroup)
    if status:
        q = q.where(InvoiceGroup.status == status)
    if match_method:
        q = q.where(InvoiceGroup.match_method == match_method)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    groups = db.scalars(q.order_by(InvoiceGroup.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [_detail(db, g).model_dump(mode="json") for g in groups],
            "page": page, "page_size": page_size, "total": total}


@router.get("/groups/{group_id}", response_model=GroupDetail)
def get_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    g = db.get(InvoiceGroup, group_id)
    if not g:
        raise HTTPException(404, detail={"code": "not_found", "message": "Group not found"})
    return _detail(db, g)


@router.post("/cross-verify", response_model=CrossVerifyResponse)
def cross_verify(body: CrossVerifyRequest, db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(body.invoice_ids))
    invs = list(db.scalars(select(Invoice).where(Invoice.id.in_(ids)).options(selectinload(Invoice.line_items))))
    if len(invs) != len(ids) or len(invs) < 2:
        raise HTTPException(404, detail={"code": "not_found", "message": "One or more invoices not found"})
    mismatched, rows = compare(invs)
    group_id = None
    if body.save_group:
        existing = next((i.group_id for i in invs if i.group_id), None)
        g = db.get(InvoiceGroup, existing) if existing else None
        if g is None:
            g = InvoiceGroup(match_key="manual:" + ",".join(sorted(str(i.id) for i in invs)),
                             match_method="manual", status="consistent", mismatched_fields=[])
            db.add(g)
            db.flush()
        for i in invs:
            i.group_id = g.id
        db.flush()
        services.refresh_group(db, g)
        db.commit()
        group_id = g.id
    return CrossVerifyResponse(mismatched_fields=mismatched, comparison=rows, group_id=group_id)
