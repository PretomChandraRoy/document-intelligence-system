"""FastAPI application: routers, authentication, error format, CORS, rate limits."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .api import documents, groups, invoices, search, system
from .config import get_settings
from .db import get_db
from .security import limiter, require_api_key

settings = get_settings()

app = FastAPI(
    title="Document Intelligence API",
    version=system.VERSION,
    description="Upload business documents, extract and validate invoice data, search and correct results.",
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "PATCH"],
                   allow_headers=["X-API-Key", "Content-Type"])


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                                                               "details": details or {}}})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return _error(exc.status_code, exc.detail.get("code", "error"), exc.detail.get("message", ""),
                      exc.detail.get("details"))
    return _error(exc.status_code, "error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return _error(422, "invalid_request", "The request is not valid", {"errors": errs})


@app.exception_handler(RateLimitExceeded)
async def rate_limited(_: Request, exc: RateLimitExceeded):
    return _error(429, "rate_limited", f"Too many requests: {exc.detail}")


@app.get("/health", tags=["system"])
@app.get("/api/v1/health", tags=["system"], include_in_schema=False)
def health(db=Depends(get_db)):
    """No authentication, so load balancers and Docker can call it."""
    return system.health_payload(db)


PREFIX = "/api/v1"
auth = [Depends(require_api_key)]
for r in (documents.router, invoices.router, search.router, groups.router, system.router):
    app.include_router(r, prefix=PREFIX, dependencies=auth)
