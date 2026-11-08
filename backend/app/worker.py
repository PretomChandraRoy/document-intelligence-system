"""Celery tasks: the four pipeline stages, each on its own queue.

    ingest  -> ocr (batches of pages, in parallel) -> extract -> post

Run workers with, for example:
    celery -A app.worker worker -Q ingest,ocr,post --concurrency 6
    celery -A app.worker worker -Q extract --concurrency 1      # GPU
"""

from __future__ import annotations

import logging

from celery import Celery, chord

from .config import get_settings
from .db import session_scope
from .models import Document, ProcessingRun
from .pipeline.llm import LLMError, get_client

log = logging.getLogger(__name__)
settings = get_settings()

celery = Celery("docintel", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_acks_late=True,               # a task is removed from the queue only after it finishes
    task_reject_on_worker_lost=True,   # ...so a crashed worker's task goes back on the queue
    worker_prefetch_multiplier=1,      # take one task at a time; OCR tasks are long
    task_always_eager=settings.task_always_eager,
    task_eager_propagates=True,
    task_routes={
        "docintel.ingest": {"queue": "ingest"},
        "docintel.ocr": {"queue": "ocr"},
        "docintel.extract": {"queue": "extract"},
        "docintel.post": {"queue": "post"},
    },
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)

STAGE_ORDER = ["ingest", "ocr", "extract", "post"]


def enqueue(document_id: str, run_id: str, from_stage: str = "ingest") -> None:
    if from_stage in ("ingest", "ocr"):
        # OCR cannot start before the pages are known, so both begin at ingest
        ingest_task.delay(document_id, run_id, from_stage)
    elif from_stage == "extract":
        extract_task.delay(document_id, run_id)
    else:
        post_task.delay(document_id, run_id)


def _guard(document_id, run_id, stage, fn):
    """Run a stage; any unexpected error marks the document failed instead of leaving it stuck."""
    try:
        return fn()
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("stage %s failed for %s", stage, document_id)
        from . import services
        with session_scope() as db:
            doc, run = db.get(Document, document_id), db.get(ProcessingRun, run_id)
            # the full traceback goes to the server log, not to users
            services.fail(db, doc, run, stage, "internal",
                          f"An unexpected error stopped the {stage} stage ({type(e).__name__}); see the server log")
        return None


@celery.task(name="docintel.ingest")
def ingest_task(document_id: str, run_id: str, from_stage: str = "ingest"):
    from . import services

    def work():
        with session_scope() as db:
            scanned = services.stage_ingest(db, document_id, run_id)
            failed = db.get(Document, document_id).status == "failed"
        if failed:
            return
        if scanned:
            n = settings.ocr_batch_pages
            batches = [scanned[i:i + n] for i in range(0, len(scanned), n)]
            chord([ocr_task.si(document_id, run_id, b) for b in batches])(extract_task.si(document_id, run_id))
        else:
            extract_task.delay(document_id, run_id)
    _guard(document_id, run_id, "ingest", work)


@celery.task(name="docintel.ocr")
def ocr_task(document_id: str, run_id: str, pages: list[int]):
    from . import services

    def work():
        with session_scope() as db:
            services.stage_ocr(db, document_id, run_id, pages)
    _guard(document_id, run_id, "ocr", work)


@celery.task(name="docintel.extract", bind=True, max_retries=3)
def extract_task(self, document_id: str, run_id: str):
    from . import services

    with session_scope() as db:
        if db.get(Document, document_id).status == "failed":
            return

    def work(client):
        with session_scope() as db:
            services.stage_extract(db, document_id, run_id, client)

    try:
        _guard(document_id, run_id, "extract", lambda: work(get_client()))
    except LLMError as e:
        if self.request.retries < self.max_retries and not settings.task_always_eager:
            raise self.retry(exc=e, countdown=2 ** (self.request.retries + 1))
        # model still unavailable: fall back to rules only, marked for review
        with session_scope() as db:
            services.event(db, run_id, "extract", f"Language model unavailable ({e}); used rules only", "warning")
        _guard(document_id, run_id, "extract", lambda: work(None))
    post_task.delay(document_id, run_id)


@celery.task(name="docintel.post")
def post_task(document_id: str, run_id: str):
    from . import services

    with session_scope() as db:
        if db.get(Document, document_id).status == "failed":
            return

    def work():
        with session_scope() as db:
            services.stage_post(db, document_id, run_id, get_client())
    _guard(document_id, run_id, "post", work)
