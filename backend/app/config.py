"""Application settings, read from environment variables (or a .env file).

Every setting has a safe default for local development except the API key,
which must be set explicitly so a deployment can never run unauthenticated
by accident.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOCINTEL_", extra="ignore")

    # security
    api_key: str = Field(min_length=16, description="Shared secret for the X-API-Key header")
    cors_origins: list[str] = ["http://localhost:3000"]
    max_file_mb: int = 200
    max_files_per_request: int = 20
    rate_limit_upload: str = "30/minute"
    rate_limit_search: str = "120/minute"

    # infrastructure
    database_url: str = "postgresql+psycopg://docintel:docintel@localhost:5432/docintel"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage"

    # language model (Ollama)
    llm_provider: str = "ollama"  # ollama | mock
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    llm_timeout_s: int = 180
    llm_num_ctx: int = 8192
    # semantic results below this cosine similarity are dropped, otherwise every
    # invoice would come back ranked; calibrate per embedding model
    semantic_min_similarity: float = 0.5

    # processing
    ocr_batch_pages: int = 20
    ocr_lang: str = "eng"
    digital_text_min_chars: int = 25  # below this a PDF page is treated as scanned
    low_confidence: float = 0.6
    max_image_pixels: int = 120_000_000  # decompression-bomb guard
    max_sheet_rows: int = 50_000

    # when true, Celery runs tasks inline (tests and single-process demos)
    task_always_eager: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
