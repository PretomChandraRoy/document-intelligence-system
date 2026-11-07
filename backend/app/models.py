"""Database tables. See docs/DATABASE.md for the reasoning behind each one."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint, func, Float,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

EMBED_DIM = 768

DOC_STATUSES = ("queued", "processing", "completed", "needs_review", "failed")
STAGES = ("ingest", "ocr", "extract", "post", "done")
REVIEW_STATUSES = ("auto_approved", "needs_review", "reviewed")
ISSUE_CODES = ("missing_field", "total_mismatch", "line_items_mismatch", "line_amount_mismatch",
               "tax_rate_mismatch", "implausible_value", "ungrounded_value", "low_confidence",
               "duplicate", "cross_mismatch")


def _check(col: str, values: tuple[str, ...]) -> CheckConstraint:
    vals = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({vals})", name=f"ck_{col}")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Timestamped, Base):
    __tablename__ = "documents"
    __table_args__ = (
        _check("status", DOC_STATUSES),
        _check("stage", STAGES),
        Index("ix_documents_status", "status"),
        Index("ix_documents_sha256", "sha256"),
        Index("ix_documents_uploaded_at", "uploaded_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    original_filename: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str] = mapped_column(String(16), default="ingest")
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    exact_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    pages: Mapped[list[Page]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                             order_by="Page.page_number")
    invoices: Mapped[list[Invoice]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                                   order_by="Invoice.page_start")
    runs: Mapped[list[ProcessingRun]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                                     order_by="ProcessingRun.attempt")
    issues: Mapped[list[ValidationIssue]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Page(Timestamped, Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page_number"),
        _check("kind", ("digital", "scanned", "sheet")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(8))
    text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    processing_ms: Mapped[int | None] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="pages")


class InvoiceGroup(Timestamped, Base):
    __tablename__ = "invoice_groups"
    __table_args__ = (
        _check("match_method", ("key", "fuzzy", "manual")),
        _check("status", ("consistent", "mismatch")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    match_key: Mapped[str] = mapped_column(Text)
    match_method: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12))
    mismatched_fields: Mapped[list] = mapped_column(JSONB, default=list)

    invoices: Mapped[list[Invoice]] = relationship(back_populates="group")


class Invoice(Timestamped, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        _check("review_status", REVIEW_STATUSES),
        _check("extraction_method", ("spreadsheet", "rules", "llm", "manual")),
        Index("ix_invoices_dedupe_key", "dedupe_key"),
        Index("ix_invoices_invoice_date", "invoice_date"),
        Index("ix_invoices_total", "total"),
        Index("ix_invoices_review_status", "review_status"),
        Index("ix_invoices_supplier_trgm", "supplier_name", postgresql_using="gin",
              postgresql_ops={"supplier_name": "gin_trgm_ops"}),
        Index("ix_invoices_customer_trgm", "customer_name", postgresql_using="gin",
              postgresql_ops={"customer_name": "gin_trgm_ops"}),
        Index("ix_invoices_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_invoices_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(Text)

    invoice_number: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    supplier_name: Mapped[str | None] = mapped_column(Text)
    customer_name: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    extraction_method: Mapped[str] = mapped_column(String(12))
    field_confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_model_output: Mapped[dict | None] = mapped_column(JSONB)
    review_status: Mapped[str] = mapped_column(String(16), default="needs_review")
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dedupe_key: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice_groups.id", ondelete="SET NULL"))

    search_text: Mapped[str | None] = mapped_column(Text)
    search_tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', coalesce(search_text, ''))",
                                                  persisted=True))
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    document: Mapped[Document] = relationship(back_populates="invoices")
    line_items: Mapped[list[LineItem]] = relationship(back_populates="invoice", cascade="all, delete-orphan",
                                                      order_by="LineItem.position")
    issues: Mapped[list[ValidationIssue]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    corrections: Mapped[list[Correction]] = relationship(back_populates="invoice", cascade="all, delete-orphan",
                                                         order_by="Correction.created_at")
    group: Mapped[InvoiceGroup | None] = relationship(back_populates="invoices")


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"),
                                                  index=True)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")


class ValidationIssue(Timestamped, Base):
    __tablename__ = "validation_issues"
    __table_args__ = (
        _check("code", ISSUE_CODES + ("file_error",)),
        _check("severity", ("error", "warning", "info")),
        Index("ix_issues_invoice", "invoice_id"),
        Index("ix_issues_document", "document_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                         ForeignKey("invoices.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))
    field: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[Document] = relationship(back_populates="issues")
    invoice: Mapped[Invoice | None] = relationship(back_populates="issues")


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"),
                                                  index=True)
    field_path: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    corrected_by: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invoice: Mapped[Invoice] = relationship(back_populates="corrections")


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        _check("trigger", ("upload", "reprocess", "bulk_reprocess")),
        _check("status", ("running", "succeeded", "failed")),
        UniqueConstraint("document_id", "attempt", name="uq_run_attempt"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    attempt: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="running")
    from_stage: Mapped[str] = mapped_column(String(16), default="ingest")
    stage_timings_ms: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="runs")
    events: Mapped[list[ProcessingEvent]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                         order_by="ProcessingEvent.id")


class ProcessingEvent(Base):
    __tablename__ = "processing_events"
    __table_args__ = (_check("level", ("info", "warning", "error")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="CASCADE"),
                                              index=True)
    stage: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(8), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[ProcessingRun] = relationship(back_populates="events")
