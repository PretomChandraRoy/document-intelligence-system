"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-07 21:31:34.853957
"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector for embeddings, pg_trgm for fuzzy name matching
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('progress_done', sa.Integer(), nullable=False),
    sa.Column('progress_total', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('exact_duplicate_of', sa.UUID(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("stage IN ('ingest', 'ocr', 'extract', 'post', 'done')", name='ck_stage'),
    sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'needs_review', 'failed')", name='ck_status'),
    sa.ForeignKeyConstraint(['exact_duplicate_of'], ['documents.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_sha256', 'documents', ['sha256'], unique=False)
    op.create_index('ix_documents_status', 'documents', ['status'], unique=False)
    op.create_index('ix_documents_uploaded_at', 'documents', ['uploaded_at'], unique=False)
    op.create_table('invoice_groups',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('match_key', sa.Text(), nullable=False),
    sa.Column('match_method', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('mismatched_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("match_method IN ('key', 'fuzzy', 'manual')", name='ck_match_method'),
    sa.CheckConstraint("status IN ('consistent', 'mismatch')", name='ck_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('invoices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('page_start', sa.Integer(), nullable=True),
    sa.Column('page_end', sa.Integer(), nullable=True),
    sa.Column('sheet_name', sa.Text(), nullable=True),
    sa.Column('invoice_number', sa.Text(), nullable=True),
    sa.Column('invoice_date', sa.Date(), nullable=True),
    sa.Column('supplier_name', sa.Text(), nullable=True),
    sa.Column('customer_name', sa.Text(), nullable=True),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('tax', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('extraction_method', sa.String(length=12), nullable=False),
    sa.Column('field_confidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('raw_model_output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('review_status', sa.String(length=16), nullable=False),
    sa.Column('reviewed_by', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dedupe_key', sa.Text(), nullable=True),
    sa.Column('group_id', sa.UUID(), nullable=True),
    sa.Column('search_text', sa.Text(), nullable=True),
    sa.Column('search_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(search_text, ''))", persisted=True), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("extraction_method IN ('spreadsheet', 'rules', 'llm', 'manual')", name='ck_extraction_method'),
    sa.CheckConstraint("review_status IN ('auto_approved', 'needs_review', 'reviewed')", name='ck_review_status'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['invoice_groups.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_invoices_customer_trgm', 'invoices', ['customer_name'], unique=False, postgresql_using='gin', postgresql_ops={'customer_name': 'gin_trgm_ops'})
    op.create_index('ix_invoices_dedupe_key', 'invoices', ['dedupe_key'], unique=False)
    op.create_index('ix_invoices_embedding', 'invoices', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_invoices_invoice_date', 'invoices', ['invoice_date'], unique=False)
    op.create_index('ix_invoices_review_status', 'invoices', ['review_status'], unique=False)
    op.create_index('ix_invoices_search_tsv', 'invoices', ['search_tsv'], unique=False, postgresql_using='gin')
    op.create_index('ix_invoices_supplier_trgm', 'invoices', ['supplier_name'], unique=False, postgresql_using='gin', postgresql_ops={'supplier_name': 'gin_trgm_ops'})
    op.create_index('ix_invoices_total', 'invoices', ['total'], unique=False)
    op.create_table('pages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('sheet_name', sa.Text(), nullable=True),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('ocr_confidence', sa.Float(), nullable=True),
    sa.Column('processing_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('digital', 'scanned', 'sheet')", name='ck_kind'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'page_number', name='uq_page_number')
    )
    op.create_table('processing_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('from_stage', sa.String(length=16), nullable=False),
    sa.Column('stage_timings_ms', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('running', 'succeeded', 'failed')", name='ck_status'),
    sa.CheckConstraint("trigger IN ('upload', 'reprocess', 'bulk_reprocess')", name='ck_trigger'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'attempt', name='uq_run_attempt')
    )
    op.create_table('corrections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('field_path', sa.Text(), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('corrected_by', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_corrections_invoice_id'), 'corrections', ['invoice_id'], unique=False)
    op.create_table('line_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_line_items_invoice_id'), 'line_items', ['invoice_id'], unique=False)
    op.create_table('processing_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("level IN ('info', 'warning', 'error')", name='ck_level'),
    sa.ForeignKeyConstraint(['run_id'], ['processing_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processing_events_run_id'), 'processing_events', ['run_id'], unique=False)
    op.create_table('validation_issues',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=True),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=8), nullable=False),
    sa.Column('field', sa.Text(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code IN ('missing_field', 'total_mismatch', 'line_items_mismatch', 'line_amount_mismatch', 'tax_rate_mismatch', 'implausible_value', 'ungrounded_value', 'low_confidence', 'duplicate', 'cross_mismatch', 'file_error')", name='ck_code'),
    sa.CheckConstraint("severity IN ('error', 'warning', 'info')", name='ck_severity'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_issues_document', 'validation_issues', ['document_id'], unique=False)
    op.create_index('ix_issues_invoice', 'validation_issues', ['invoice_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_issues_invoice', table_name='validation_issues')
    op.drop_index('ix_issues_document', table_name='validation_issues')
    op.drop_table('validation_issues')
    op.drop_index(op.f('ix_processing_events_run_id'), table_name='processing_events')
    op.drop_table('processing_events')
    op.drop_index(op.f('ix_line_items_invoice_id'), table_name='line_items')
    op.drop_table('line_items')
    op.drop_index(op.f('ix_corrections_invoice_id'), table_name='corrections')
    op.drop_table('corrections')
    op.drop_table('processing_runs')
    op.drop_table('pages')
    op.drop_index('ix_invoices_total', table_name='invoices')
    op.drop_index('ix_invoices_supplier_trgm', table_name='invoices', postgresql_using='gin', postgresql_ops={'supplier_name': 'gin_trgm_ops'})
    op.drop_index('ix_invoices_search_tsv', table_name='invoices', postgresql_using='gin')
    op.drop_index('ix_invoices_review_status', table_name='invoices')
    op.drop_index('ix_invoices_invoice_date', table_name='invoices')
    op.drop_index('ix_invoices_embedding', table_name='invoices', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('ix_invoices_dedupe_key', table_name='invoices')
    op.drop_index('ix_invoices_customer_trgm', table_name='invoices', postgresql_using='gin', postgresql_ops={'customer_name': 'gin_trgm_ops'})
    op.drop_table('invoices')
    op.drop_table('invoice_groups')
    op.drop_index('ix_documents_uploaded_at', table_name='documents')
    op.drop_index('ix_documents_status', table_name='documents')
    op.drop_index('ix_documents_sha256', table_name='documents')
    op.drop_table('documents')
