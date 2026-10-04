"""Central configuration, read from environment variables (or a local .env file)."""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional in production
    pass


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    # "ollama" (local, free) or "openai" (any OpenAI-compatible API: OpenAI, Groq,
    # OpenRouter, Together, a hosted Ollama/vLLM, ...). Use "openai" on Vercel.
    provider: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

    # --- Ollama ---
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "phi3:mini")
    # Vision model used to read text out of images / scanned PDFs.
    ollama_vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "llava")
    ollama_num_ctx: int = _int("OLLAMA_NUM_CTX", 4096)

    # --- OpenAI-compatible ---
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    temperature: float = _float("LLM_TEMPERATURE", 0.5)
    request_timeout: float = _float("LLM_TIMEOUT_SECONDS", 300)

    # How much text fits into ONE model call, and how big each piece is when a long
    # text has to be split. Small local models (phi3:mini, 4k context) need small
    # values; hosted models can take far more. Override with env vars if you like.
    single_pass_chars: int = _int(
        "SINGLE_PASS_CHARS", 7000 if os.getenv("LLM_PROVIDER", "ollama").lower() == "ollama" else 60000
    )
    chunk_chars: int = _int(
        "CHUNK_CHARS", 5000 if os.getenv("LLM_PROVIDER", "ollama").lower() == "ollama" else 40000
    )
    # Parallel model calls while condensing a long text (a local Ollama handles one at a time).
    map_concurrency: int = _int(
        "MAP_CONCURRENCY", 1 if os.getenv("LLM_PROVIDER", "ollama").lower() == "ollama" else 4
    )

    # Per-file upload cap. Vercel serverless functions reject request bodies over ~4.5 MB.
    max_upload_mb: float = _float("MAX_UPLOAD_MB", 4.0)

    # Comma-separated list of allowed frontend origins, or "*".
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    @property
    def text_model(self) -> str:
        return self.ollama_model if self.provider == "ollama" else self.openai_model

    @property
    def vision_model(self) -> str:
        return self.ollama_vision_model if self.provider == "ollama" else self.openai_vision_model


settings = Settings()
