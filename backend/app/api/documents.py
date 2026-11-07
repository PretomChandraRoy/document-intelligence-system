"""Upload, status, history, files and reprocessing."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import services, storage
from ..config import get_settings
from ..db import get_db
from ..models import Document, Invoice, ProcessingRun, ValidationIssue
from ..pipeline.filetypes import ALLOWED_EXTENSIONS, extension_of, sniff
from ..schemas import (BulkReprocessRequest, DocumentBrief, DocumentDetail, InvoiceBrief, ReprocessRequest,
                       RunOut, RunWithEvents, UploadAccepted, UploadRejected, UploadResponse)
from ..security import limiter

router = APIRouter(prefix="/documents", tags=["documents"])

MEDIA = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png", "tiff": "image/tiff",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "xls": "application/vnd.ms-excel", "csv": "text/csv"}


def not_found(what="Document"):
    return HTTPException(404, detail={"code": "not_found", "message": f"{what} not found"})


@router.post("", status_code=202, response_model=UploadResponse)
@limiter.limit(lambda: get_settings().rate_limit_upload)
def upload(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    s = get_settings()
    if len(files) > s.max_files_per_request:
        raise HTTPException(413, detail={"code": "too_many_files",
                                         "message": f"At most {s.max_files_per_request} files per request"})
    from ..worker import enqueue
    accepted, rejected, to_queue = [], [], []
    for f in files:
        name = (f.filename or "unnamed")[:255]
        ext = extension_of(name)
        try:
            stored = storage.save_stream(f.file, s.max_file_mb * 1024 * 1024)
        except storage.FileTooLarge:
            rejected.append(UploadRejected(filename=name, code="file_too_large",
                                           message=f"Files may be at most {s.max_file_mb} MB"))
            continue
        detected = sniff(stored.head, storage.absolute(stored.relative_path))
        if ext not in ALLOWED_EXTENSIONS and detected in (None, "empty"):
            rejected.append(UploadRejected(filename=name, code="unsupported_format",
                                           message="Accepted formats: PDF, JPG, PNG, TIFF, XLSX, XLS, CSV"))
            continue
        # the declared format is the extension if it is an allowed one; the
        # ingest stage then fails the document if the content disagrees
        fmt = ext if ext in ALLOWED_EXTENSIONS else detected
        dup = db.scalar(select(Document.id).where(Document.sha256 == stored.sha256).order_by(Document.uploaded_at))
        doc = Document(original_filename=name, sha256=stored.sha256, format=fmt, size_bytes=stored.size_bytes,
                       storage_path=stored.relative_path, exact_duplicate_of=dup)
        db.add(doc)
        db.flush()
        run = services.start_run(db, doc, "upload")
        to_queue.append((str(doc.id), str(run.id)))
        accepted.append(UploadAccepted(id=doc.id, filename=name, format=fmt, status=doc.status,
                                       exact_duplicate_of=dup))
    db.commit()
    for doc_id, run_id in to_queue:
        enqueue(doc_id, run_id)
    return UploadResponse(accepted=accepted, rejected=rejected)


def _brief(db: Session, docs: list[Document]) -> list[dict]:
    ids = [d.id for d in docs]
    counts = dict(db.execute(select(Invoice.document_id, func.count()).where(Invoice.document_id.in_(ids))
                             .group_by(Invoice.document_id)).all()) if ids else {}
    out = []
    for d in docs:
        b = DocumentBrief.model_validate(d)
        b.invoice_count = counts.get(d.id, 0)
        out.append(b.model_dump(by_alias=True))
    return out


@router.get("")
def list_documents(status: str | None = None, format: str | None = None, page: int = Query(1, ge=1),
                   page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    q = select(Document)
    if status:
        q = q.where(Document.status == status)
    if format:
        q = q.where(Document.format == format)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    docs = list(db.scalars(q.order_by(Document.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return {"items": _brief(db, docs), "page": page, "page_size": page_size, "total": total}


@router.get("/{doc_id}")
def get_document(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.scalar(select(Document).where(Document.id == doc_id)
                    .options(selectinload(Document.pages), selectinload(Document.invoices),
                             selectinload(Document.runs)))
    if not doc:
        raise not_found()
    counts = dict(db.execute(select(ValidationIssue.invoice_id, func.count())
                             .where(ValidationIssue.document_id == doc.id, ValidationIssue.resolved.is_(False))
                             .group_by(ValidationIssue.invoice_id)).all())
    invoices = []
    for inv in doc.invoices:
        b = InvoiceBrief.model_validate(inv)
        b.issue_count = counts.get(inv.id, 0)
        invoices.append(b)
    detail = DocumentDetail.model_validate(doc)
    detail.invoices = invoices
    detail.invoice_count = len(invoices)
    detail.last_run = RunOut.model_validate(doc.runs[-1]) if doc.runs else None
    return detail.model_dump(by_alias=True, mode="json")


@router.get("/{doc_id}/history", response_model=list[RunWithEvents])
def history(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    if not db.get(Document, doc_id):
        raise not_found()
    runs = db.scalars(select(ProcessingRun).where(ProcessingRun.document_id == doc_id)
                      .options(selectinload(ProcessingRun.events)).order_by(ProcessingRun.attempt.desc()))
    return list(runs)


@router.get("/{doc_id}/file")
def download(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise not_found()
    safe = "".join(c for c in doc.original_filename if c.isalnum() or c in "._- ")[:120] or "document"
    return FileResponse(storage.absolute(doc.storage_path), media_type=MEDIA.get(doc.format),
                        filename=safe, content_disposition_type="inline")


@router.get("/{doc_id}/pages/{n}/image")
def page_image(doc_id: uuid.UUID, n: int, dpi: int = Query(110, ge=50, le=200), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise not_found()
    if doc.format not in ("pdf", "jpg", "png", "tiff") or not doc.page_count or not 1 <= n <= doc.page_count:
        raise not_found("Page")
    from ..pipeline.ingest import render_image_page, render_pdf_page
    try:
        im = render_pdf_page(storage.absolute(doc.storage_path), n, dpi) if doc.format == "pdf" \
            else render_image_page(storage.absolute(doc.storage_path), n)
    except Exception:
        raise not_found("Page")
    im.thumbnail((1400, 1980))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/reprocess-failed", status_code=202)
def reprocess_failed(body: BulkReprocessRequest | None = None, db: Session = Depends(get_db)):
    from ..worker import enqueue
    q = select(Document).where(Document.status == "failed")
    if body and body.document_ids:
        q = q.where(Document.id.in_(body.document_ids))
    jobs = []
    for doc in db.scalars(q):
        run = services.start_run(db, doc, "bulk_reprocess")
        jobs.append((str(doc.id), str(run.id)))
    db.commit()
    for d, r in jobs:
        enqueue(d, r)
    return {"queued": len(jobs)}


@router.post("/{doc_id}/reprocess", status_code=202, response_model=RunOut)
def reprocess(doc_id: uuid.UUID, body: ReprocessRequest | None = None, db: Session = Depends(get_db)):
    from ..worker import enqueue
    doc = db.get(Document, doc_id)
    if not doc:
        raise not_found()
    if doc.status in ("queued", "processing"):
        raise HTTPException(409, detail={"code": "busy", "message": "The document is still being processed"})
    stage = (body.from_stage if body else "ingest")
    if stage != "ingest" and not doc.pages:
        stage = "ingest"  # nothing to reuse
    run = services.start_run(db, doc, "reprocess", stage)
    db.commit()
    enqueue(str(doc.id), str(run.id), stage)
    db.refresh(run)
    return run
