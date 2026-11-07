"""Request and response shapes for the REST API (also the OpenAPI schema).

Money is sent as strings so JavaScript never turns 0.1 into 0.1000000001.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: None if v is None else f"{v:.2f}", return_type=str | None)]
Qty = Annotated[Decimal, PlainSerializer(lambda v: None if v is None else format(v.normalize(), "f"),
                                         return_type=str | None)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = {}


class Page_(BaseModel):
    items: list
    page: int
    page_size: int
    total: int


# -- documents ---------------------------------------------------------------------
class UploadAccepted(BaseModel):
    id: uuid.UUID
    filename: str
    format: str
    status: str
    exact_duplicate_of: uuid.UUID | None = None


class UploadRejected(BaseModel):
    filename: str
    code: str
    message: str


class UploadResponse(BaseModel):
    accepted: list[UploadAccepted]
    rejected: list[UploadRejected]


class PageOut(ORM):
    page_number: int
    kind: str
    sheet_name: str | None
    ocr_confidence: float | None


class InvoiceBrief(ORM):
    id: uuid.UUID
    document_id: uuid.UUID
    invoice_number: str | None
    invoice_date: date | None
    supplier_name: str | None
    customer_name: str | None
    total: Money | None
    currency: str | None
    review_status: str
    extraction_method: str
    issue_count: int = 0
    group_id: uuid.UUID | None = None


class RunOut(ORM):
    id: uuid.UUID
    attempt: int
    trigger: str
    from_stage: str
    status: str
    stage_timings_ms: dict
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class DocumentBrief(ORM):
    id: uuid.UUID
    original_filename: str = Field(serialization_alias="filename")
    format: str
    status: str
    stage: str
    progress_done: int
    progress_total: int
    page_count: int | None
    uploaded_at: datetime
    error_code: str | None
    invoice_count: int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class DocumentDetail(DocumentBrief):
    size_bytes: int
    sha256: str
    error_message: str | None
    exact_duplicate_of: uuid.UUID | None
    pages: list[PageOut]
    invoices: list[InvoiceBrief]
    last_run: RunOut | None = None


class EventOut(ORM):
    stage: str
    level: str
    message: str
    created_at: datetime


class RunWithEvents(RunOut):
    events: list[EventOut]


class ReprocessRequest(BaseModel):
    from_stage: Literal["ingest", "ocr", "extract", "post"] = "ingest"


class BulkReprocessRequest(BaseModel):
    document_ids: list[uuid.UUID] | None = None


# -- invoices ------------------------------------------------------------------------
class LineItemOut(ORM):
    position: int
    description: str | None
    quantity: Qty | None
    unit_price: Money | None
    amount: Money | None


class IssueOut(ORM):
    id: uuid.UUID
    code: str
    severity: str
    field: str | None
    message: str
    details: dict
    resolved: bool


class GroupBrief(ORM):
    id: uuid.UUID
    status: str
    match_method: str
    mismatched_fields: list


class InvoiceDetail(ORM):
    id: uuid.UUID
    document_id: uuid.UUID
    page_start: int | None
    page_end: int | None
    sheet_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    supplier_name: str | None
    customer_name: str | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    currency: str | None
    line_items: list[LineItemOut]
    extraction_method: str
    field_confidence: dict
    evidence: dict
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    issues: list[IssueOut]
    group: GroupBrief | None
    document_filename: str | None = None


class LineItemIn(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


class CorrectionFields(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)


class CorrectionRequest(BaseModel):
    corrected_by: str = Field(min_length=1, max_length=100)
    fields: CorrectionFields = CorrectionFields()
    line_items: list[LineItemIn] | None = None
    note: str | None = Field(None, max_length=1000)


class ReviewRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=100)
    # "approve" requires that no errors remain; "accept_with_issues" records that a
    # person checked the errors (for example, a supplier's arithmetic mistake) and accepts them
    decision: Literal["approve", "accept_with_issues"] = "approve"
    note: str | None = Field(None, max_length=1000)


class CorrectionOut(ORM):
    field_path: str
    old_value: str | None
    new_value: str | None
    corrected_by: str
    note: str | None
    created_at: datetime


# -- search and groups ------------------------------------------------------------------
class SearchHit(BaseModel):
    invoice_id: uuid.UUID
    document_id: uuid.UUID
    invoice_number: str | None
    supplier_name: str | None
    customer_name: str | None
    invoice_date: date | None
    total: Money | None
    currency: str | None
    review_status: str
    score: float
    keyword_rank: int | None
    semantic_rank: int | None
    snippet: str | None


class SearchResponse(BaseModel):
    mode: str
    query: str | None
    results: list[SearchHit]


class GroupMember(BaseModel):
    invoice_id: uuid.UUID
    document_id: uuid.UUID
    document: str
    format: str


class GroupDetail(BaseModel):
    id: uuid.UUID
    status: str
    match_method: str
    match_key: str
    mismatched_fields: list
    members: list[GroupMember]
    comparison: list[dict]


class CrossVerifyRequest(BaseModel):
    invoice_ids: list[uuid.UUID] = Field(min_length=2, max_length=10)
    save_group: bool = False


class CrossVerifyResponse(BaseModel):
    mismatched_fields: list[str]
    comparison: list[dict]
    group_id: uuid.UUID | None = None
