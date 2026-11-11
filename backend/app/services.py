"""Database-facing work for each processing stage.

The Celery tasks in worker.py are thin wrappers around these functions, so
the same code runs in a worker, in a test, or in a one-off script.

Every stage is idempotent: it removes its own earlier output for the
document before writing new output, so a retried or repeated task never
duplicates rows.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from . import storage
from .config import get_settings
from .models import (Correction, Document, Invoice, InvoiceGroup, LineItem, Page, ProcessingEvent,
                     ProcessingRun, ValidationIssue)
from .pipeline.extract import extract_invoice
from .pipeline.ingest import IngestError, ingest, render_page
from .pipeline.llm import LLMClient
from .pipeline.matching import compare, dedupe_key, norm_supplier
from .pipeline.ocr import ocr_image
from .pipeline.schema import ExtractedInvoice
from .pipeline.segment import segment_pages
from .pipeline.spreadsheet import parse_workbook
from .pipeline.validate import review_status, validate

def now():
    return datetime.now(timezone.utc)


# -- runs and events ---------------------------------------------------------------
def start_run(db: Session, doc: Document, trigger: str, from_stage: str = "ingest") -> ProcessingRun:
    attempt = (db.scalar(select(func.max(ProcessingRun.attempt)).where(ProcessingRun.document_id == doc.id)) or 0) + 1
    run = ProcessingRun(document_id=doc.id, attempt=attempt, trigger=trigger, from_stage=from_stage,
                        stage_timings_ms={})
    doc.status, doc.stage = "queued", from_stage
    doc.error_code = doc.error_message = None
    db.add(run)
    db.flush()
    return run


def event(db: Session, run_id, stage: str, message: str, level: str = "info") -> None:
    db.add(ProcessingEvent(run_id=run_id, stage=stage, message=message, level=level))


def _timing(run: ProcessingRun, stage: str, ms: int) -> None:
    t = dict(run.stage_timings_ms or {})
    t[stage] = t.get(stage, 0) + ms
    run.stage_timings_ms = t


def fail(db: Session, doc: Document, run: ProcessingRun, stage: str, code: str, message: str) -> None:
    doc.status, doc.stage = "failed", stage
    doc.error_code, doc.error_message = code, message
    run.status, run.error, run.finished_at = "failed", f"{code}: {message}", now()
    event(db, run.id, stage, message, "error")


# -- stage 1: ingest -----------------------------------------------------------------
def stage_ingest(db: Session, doc_id, run_id) -> list[int]:
    """Returns the page numbers that need OCR."""
    s = get_settings()
    doc, run = db.get(Document, doc_id), db.get(ProcessingRun, run_id)
    t0 = time.perf_counter()
    doc.status, doc.stage = "processing", "ingest"
    clear_invoices(db, doc.id)
    db.execute(delete(ValidationIssue).where(ValidationIssue.document_id == doc.id))
    db.execute(delete(Page).where(Page.document_id == doc.id))
    try:
        result = ingest(storage.absolute(doc.storage_path), doc.format, min_chars=s.digital_text_min_chars,
                        max_pixels=s.max_image_pixels, max_rows=s.max_sheet_rows)
    except IngestError as e:
        fail(db, doc, run, "ingest", e.code, e.message)
        _timing(run, "ingest", int((time.perf_counter() - t0) * 1000))
        return []
    for w in result.warnings:
        event(db, run.id, "ingest", w, "warning")
    for p in result.pages:
        db.add(Page(document_id=doc.id, page_number=p.number, kind=p.kind, text=p.text,
                    sheet_name=p.sheet_name))
    doc.page_count = len(result.pages)
    doc.progress_total = len(result.pages)
    scanned = [p.number for p in result.pages if p.kind == "scanned"]
    doc.progress_done = len(result.pages) - len(scanned)
    doc.stage = "ocr" if scanned else "extract"
    kinds = {k: sum(p.kind == k for p in result.pages) for k in ("digital", "scanned", "sheet")}
    event(db, run.id, "ingest", f"{len(result.pages)} page(s): " +
          ", ".join(f"{v} {k}" for k, v in kinds.items() if v))
    _timing(run, "ingest", int((time.perf_counter() - t0) * 1000))
    return scanned


# -- stage 2: OCR ------------------------------------------------------------------------
def stage_ocr(db: Session, doc_id, run_id, page_numbers: list[int]) -> None:
    s = get_settings()
    doc = db.get(Document, doc_id)
    path = storage.absolute(doc.storage_path)
    t0 = time.perf_counter()
    for n in page_numbers:
        page = db.scalar(select(Page).where(Page.document_id == doc.id, Page.page_number == n))
        res = ocr_image(render_page(path, doc.format, n), lang=s.ocr_lang)
        page.text, page.ocr_confidence, page.processing_ms = res.text, round(res.confidence, 1), res.ms
        if res.confidence < 60:
            event(db, run_id, "ocr", f"Page {n}: OCR confidence {res.confidence:.0f}, image quality is poor",
                  "warning")
    db.execute(update(Document).where(Document.id == doc.id)
               .values(progress_done=Document.progress_done + len(page_numbers)))
    ms = int((time.perf_counter() - t0) * 1000)
    run = db.get(ProcessingRun, run_id, with_for_update=True)
    _timing(run, "ocr", ms)


# -- stage 3: extract -----------------------------------------------------------------------
def stage_extract(db: Session, doc_id, run_id, client: LLMClient | None, llm_only: bool = False) -> int:
    doc, run = db.get(Document, doc_id), db.get(ProcessingRun, run_id)
    t0 = time.perf_counter()
    doc.status, doc.stage = "processing", "extract"
    clear_invoices(db, doc.id)
    db.execute(delete(ValidationIssue).where(ValidationIssue.document_id == doc.id))
    pages = list(db.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.page_number)))

    extracted: list[ExtractedInvoice] = []
    if doc.format in ("xlsx", "xls", "csv"):
        # tables are not stored, so re-read the file (fast for spreadsheets)
        res = ingest(storage.absolute(doc.storage_path), doc.format)
        extracted = parse_workbook(res.pages)
        if not extracted:
            text = "\n\n".join(p.text or "" for p in pages)
            extracted = [extract_invoice(text, client, force_llm=True)]
            event(db, run.id, "extract", "Spreadsheet layout not recognised; read with the language model")
    else:
        segments = segment_pages([(p.page_number, p.text or "") for p in pages])
        by_num = {p.page_number: p for p in pages}
        for seg in segments:
            if not seg.text.strip():
                event(db, run.id, "extract", f"Pages {seg.start}-{seg.end}: no readable text", "warning")
                continue
            confs = [by_num[n].ocr_confidence for n in seg.pages if by_num[n].ocr_confidence is not None]
            ocr_conf = min(confs) if confs else None
            inv = extract_invoice(seg.text, client, page_texts=seg.texts, ocr_confidence=ocr_conf,
                                  llm_only=llm_only)
            inv.page_start, inv.page_end = seg.start, seg.end
            extracted.append(inv)
        if len(segments) > 1:
            event(db, run.id, "extract", f"Split into {len(segments)} invoices")

    for e in extracted:
        save_invoice(db, doc, e)
    methods = {m: sum(e.method == m for e in extracted) for m in ("spreadsheet", "rules", "llm")}
    event(db, run.id, "extract", f"{len(extracted)} invoice(s) extracted: " +
          ", ".join(f"{v} by {k}" for k, v in methods.items() if v))
    _timing(run, "extract", int((time.perf_counter() - t0) * 1000))
    doc.stage = "post"
    return len(extracted)


def clear_invoices(db: Session, doc_id) -> None:
    """Delete a document's invoices before re-extracting, and tidy the groups they were in.

    A group left with one member is no longer a duplicate, so it is removed
    and that member's duplicate and cross-check issues are cleared.
    """
    group_ids = set(db.scalars(select(Invoice.group_id).where(Invoice.document_id == doc_id,
                                                             Invoice.group_id.is_not(None))))
    db.execute(delete(Invoice).where(Invoice.document_id == doc_id))
    db.flush()
    for gid in group_ids:
        group = db.get(InvoiceGroup, gid)
        rest = list(db.scalars(select(Invoice).where(Invoice.group_id == gid)))
        if len(rest) >= 2:
            refresh_group(db, group)
            continue
        for inv in rest:
            inv.group_id = None
            db.execute(delete(ValidationIssue).where(ValidationIssue.invoice_id == inv.id,
                                                     ValidationIssue.code.in_(["duplicate", "cross_mismatch"]),
                                                     ValidationIssue.resolved.is_(False)))
        db.flush()
        db.delete(group)


def save_invoice(db: Session, doc: Document, e: ExtractedInvoice) -> Invoice:
    s = get_settings()
    inv = Invoice(document_id=doc.id, page_start=e.page_start, page_end=e.page_end, sheet_name=e.sheet_name,
                  invoice_number=e.invoice_number, invoice_date=e.invoice_date, supplier_name=e.supplier_name,
                  customer_name=e.customer_name, subtotal=e.subtotal, tax=e.tax, total=e.total,
                  currency=e.currency, extraction_method=e.method, field_confidence=e.confidence,
                  evidence=e.evidence, raw_model_output=e.raw_model_output,
                  dedupe_key=dedupe_key(e.supplier_name, e.invoice_number),
                  review_status="needs_review")
    inv.line_items = [LineItem(position=i + 1, description=li.description, quantity=li.quantity,
                               unit_price=li.unit_price, amount=li.amount) for i, li in enumerate(e.line_items)]
    db.add(inv)
    db.flush()
    issues = validate(inv, confidence=e.confidence, warnings=e.warnings, tax_rate=e.tax_rate,
                      low_confidence=s.low_confidence)
    _store_issues(db, inv, issues)
    inv.review_status = review_status(issues)
    # keep the printed tax rate for re-validation after corrections
    if e.tax_rate is not None:
        inv.evidence = {**inv.evidence, "_tax_rate": str(e.tax_rate)}
    return inv


def _store_issues(db: Session, inv: Invoice, issues: list[dict]) -> None:
    for i in issues:
        db.add(ValidationIssue(document_id=inv.document_id, invoice_id=inv.id, **i))


# -- stage 4: post (matching, indexing, final status) -----------------------------------------
def stage_post(db: Session, doc_id, run_id, client: LLMClient | None) -> None:
    doc, run = db.get(Document, doc_id), db.get(ProcessingRun, run_id)
    t0 = time.perf_counter()
    invoices = list(db.scalars(select(Invoice).where(Invoice.document_id == doc.id)
                               .options(selectinload(Invoice.line_items))))
    for inv in invoices:
        match_invoice(db, inv)
    index_invoices(db, doc, invoices, client, run.id)
    db.flush()
    finish(db, doc, run)
    _timing(run, "post", int((time.perf_counter() - t0) * 1000))


def finish(db: Session, doc: Document, run: ProcessingRun) -> None:
    invoices = list(db.scalars(select(Invoice).where(Invoice.document_id == doc.id)))
    if not invoices:
        doc.status, doc.error_code = "failed", "no_invoice_found"
        doc.error_message = "No invoice could be read from this document"
        run.status = "failed"
        event(db, run.id, "post", doc.error_message, "error")
    else:
        doc.status = "needs_review" if any(i.review_status == "needs_review" for i in invoices) else "completed"
        doc.error_code = doc.error_message = None   # a stage that succeeds on retry leaves no stale error
        run.status = "succeeded"
    doc.stage = "done"
    doc.progress_done = doc.progress_total
    run.finished_at = now()


def reconcile_status(db: Session, doc_id) -> None:
    """Re-derive the status of this document and of every document grouped with it.

    Two related documents (a PDF and its Excel record, say) can finish their
    post stages at the same moment. Each stage runs in its own transaction, so
    when one marks the other's invoice for review, the other may still be
    running and then save its own earlier verdict ("completed"). Called after
    the post stage has committed, this reads the committed invoices and puts
    the document status right. Only finished documents are touched.
    """
    group_ids = select(Invoice.group_id).where(Invoice.document_id == doc_id, Invoice.group_id.is_not(None))
    related = select(Invoice.document_id).where(Invoice.group_id.in_(group_ids))
    docs = db.scalars(select(Document).where((Document.id == doc_id) | Document.id.in_(related))
                      .with_for_update())
    for d in docs:
        if d.status not in ("completed", "needs_review"):
            continue
        statuses = list(db.scalars(select(Invoice.review_status).where(Invoice.document_id == d.id)))
        if statuses:
            d.status = "needs_review" if "needs_review" in statuses else "completed"


def match_invoice(db: Session, inv: Invoice) -> None:
    """Group this invoice with the same invoice in other documents, then compare."""
    candidates: list[Invoice] = []
    method = "key"
    if inv.dedupe_key:
        candidates = list(db.scalars(select(Invoice).where(Invoice.dedupe_key == inv.dedupe_key,
                                                           Invoice.id != inv.id)))
    elif inv.total is not None and inv.invoice_date is not None and inv.supplier_name:
        method = "fuzzy"
        candidates = list(db.scalars(select(Invoice).where(
            Invoice.id != inv.id, Invoice.total == inv.total, Invoice.invoice_date == inv.invoice_date,
            func.similarity(Invoice.supplier_name, inv.supplier_name) > 0.6)))
    if not candidates:
        return
    group = next((c.group for c in candidates if c.group_id), None)
    if group is None:
        group = InvoiceGroup(match_key=inv.dedupe_key or f"fuzzy:{norm_supplier(inv.supplier_name)}|{inv.total}|{inv.invoice_date}",
                             match_method=method, status="consistent", mismatched_fields=[])
        db.add(group)
        db.flush()
    for c in candidates + [inv]:
        c.group_id = group.id
    db.flush()
    refresh_group(db, group)


def refresh_group(db: Session, group: InvoiceGroup) -> None:
    members = list(db.scalars(select(Invoice).where(Invoice.group_id == group.id)
                              .options(selectinload(Invoice.line_items), selectinload(Invoice.document))))
    mismatched, _ = compare(members)
    group.status = "mismatch" if mismatched else "consistent"
    group.mismatched_fields = mismatched
    for m in members:
        db.execute(delete(ValidationIssue).where(ValidationIssue.invoice_id == m.id,
                                                 ValidationIssue.code.in_(["duplicate", "cross_mismatch"]),
                                                 ValidationIssue.resolved.is_(False)))
        others = [o for o in members if o.id != m.id]
        names = ", ".join(sorted({o.document.original_filename for o in others}))
        db.add(ValidationIssue(document_id=m.document_id, invoice_id=m.id, code="duplicate", severity="warning",
                               field="invoice_number",
                               message=f"The same invoice also appears in: {names}",
                               details={"group_id": str(group.id), "documents": [str(o.document_id) for o in others]}))
        for f in mismatched:
            db.add(ValidationIssue(document_id=m.document_id, invoice_id=m.id, code="cross_mismatch",
                                   severity="error", field=f,
                                   message=f"The {f.replace('_', ' ')} differs from the copy in {names}",
                                   details={"group_id": str(group.id)}))
        if m.review_status != "reviewed":
            m.review_status = "needs_review"
        # the other document's status may change too
        doc = m.document
        if doc.status == "completed":
            doc.status = "needs_review"


def summary_text(inv: Invoice) -> str:
    items = "; ".join(li.description or "" for li in inv.line_items[:40])
    return (f"Invoice {inv.invoice_number or ''} from {inv.supplier_name or 'unknown supplier'} "
            f"to {inv.customer_name or 'unknown customer'} dated {inv.invoice_date or ''}. "
            f"Items: {items}. Total {inv.total or ''} {inv.currency or ''}.")


def index_invoices(db: Session, doc: Document, invoices: list[Invoice], client: LLMClient | None, run_id) -> None:
    pages = {p.page_number: p.text or "" for p in db.scalars(select(Page).where(Page.document_id == doc.id))}
    for inv in invoices:
        rng = range(inv.page_start or 1, (inv.page_end or len(pages)) + 1)
        page_text = "\n".join(pages.get(n, "") for n in rng)[:20000]
        fields = " ".join(str(v) for v in (inv.invoice_number, inv.supplier_name, inv.customer_name,
                                            inv.currency, inv.total, inv.invoice_date) if v)
        inv.search_text = f"{fields}\n{' '.join(li.description or '' for li in inv.line_items)}\n{page_text}"
    if client is None or not invoices:
        return
    try:
        vecs = client.embed([summary_text(i) for i in invoices])
        for inv, v in zip(invoices, vecs):
            inv.embedding = v
    except Exception as e:  # search still works by keyword without embeddings
        event(db, run_id, "post", f"Embedding failed, semantic search unavailable for this document: {e}", "warning")


# -- corrections ----------------------------------------------------------------------------------
EDITABLE = ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")


def apply_correction(db: Session, inv: Invoice, fields: dict, line_items: list[dict] | None, by: str,
                     note: str | None) -> list[str]:
    changed = []
    conf = dict(inv.field_confidence or {})
    for f, new in fields.items():
        old = getattr(inv, f)
        if (str(old) if old is not None else None) == (str(new) if new is not None else None):
            continue
        db.add(Correction(invoice_id=inv.id, field_path=f, old_value=None if old is None else str(old),
                          new_value=None if new is None else str(new), corrected_by=by, note=note))
        setattr(inv, f, new)
        conf[f] = 1.0
        changed.append(f)
    if line_items is not None:
        old_desc = [(li.description, str(li.quantity), str(li.unit_price), str(li.amount)) for li in inv.line_items]
        new_desc = [(li.get("description"), str(li.get("quantity")), str(li.get("unit_price")), str(li.get("amount")))
                    for li in line_items]
        if old_desc != new_desc:
            db.add(Correction(invoice_id=inv.id, field_path="line_items", old_value=repr(old_desc),
                              new_value=repr(new_desc), corrected_by=by, note=note))
            inv.line_items = [LineItem(position=i + 1, description=li.get("description"),
                                       quantity=li.get("quantity"), unit_price=li.get("unit_price"),
                                       amount=li.get("amount")) for i, li in enumerate(line_items)]
            conf["line_items"] = 1.0
            changed.append("line_items")
    if not changed:
        return []
    inv.field_confidence = conf
    inv.extraction_method = "manual"
    inv.dedupe_key = dedupe_key(inv.supplier_name, inv.invoice_number)
    db.flush()
    revalidate(db, inv)
    inv.reviewed_by, inv.reviewed_at = by, now()
    return changed


def revalidate(db: Session, inv: Invoice) -> None:
    s = get_settings()
    db.refresh(inv, ["line_items"])
    rate = inv.evidence.get("_tax_rate") if inv.evidence else None
    issues = validate(inv, confidence=inv.field_confidence, tax_rate=Decimal(rate) if rate else None,
                      low_confidence=s.low_confidence)
    # mark old field issues resolved if they no longer apply; replace the rest
    current = {(i["code"], i["field"]) for i in issues}
    for old in db.scalars(select(ValidationIssue).where(ValidationIssue.invoice_id == inv.id,
                                                        ValidationIssue.resolved.is_(False),
                                                        ValidationIssue.code.notin_(["duplicate", "cross_mismatch"]))):
        if (old.code, old.field) in current:
            db.delete(old)
        else:
            old.resolved = True
    _store_issues(db, inv, issues)
    db.flush()
    if inv.group_id:
        refresh_group(db, db.get(InvoiceGroup, inv.group_id))
    elif inv.dedupe_key:
        match_invoice(db, inv)
    db.flush()
    blocking = db.scalar(select(func.count()).select_from(ValidationIssue).where(
        ValidationIssue.invoice_id == inv.id, ValidationIssue.severity == "error",
        ValidationIssue.resolved.is_(False)))
    inv.review_status = "needs_review" if blocking else "reviewed"
    doc = db.get(Document, inv.document_id)
    others = db.scalars(select(Invoice.review_status).where(Invoice.document_id == doc.id)).all()
    doc.status = "needs_review" if "needs_review" in others else "completed"
