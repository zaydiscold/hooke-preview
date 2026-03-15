import os
from dataclasses import dataclass
from pathlib import Path

# Load .env from project root when present (no-op if already set in environment).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    # --- Nebius Token Factory (hackathon credits) ---
    nebius_api_key: str = os.getenv(
        "NEBIUS_API_KEY",
        "",
    )
    nebius_base_url: str = os.getenv(
        "NEBIUS_BASE_URL",
        "https://api.tokenfactory.nebius.com/v1/",
    )
    nebius_model: str = os.getenv(
        "NEBIUS_MODEL",
        "meta-llama/Llama-3.3-70B-Instruct",
    )
    nebius_synthesis_model: str = os.getenv(
        "NEBIUS_SYNTHESIS_MODEL",
        "deepseek-ai/DeepSeek-V3-0324-fast",
    )

    # --- OpenRouter (fast/cheap orchestration calls) ---
    openrouter_api_key: str = os.getenv(
        "OPENROUTER_API_KEY",
        "",
    )
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
    )
    openrouter_fast_model: str = os.getenv(
        "OPENROUTER_FAST_MODEL",
        "google/gemini-2.5-flash",
    )
    openrouter_research_model: str = os.getenv(
        "OPENROUTER_RESEARCH_MODEL",
        "openai/gpt-5.4",
    )
    openrouter_brief_model: str = os.getenv(
        "OPENROUTER_BRIEF_MODEL",
        "anthropic/claude-opus-4.6",
    )

    # --- External APIs ---
    tavily_api_key: str = os.getenv(
        "TAVILY_API_KEY",
        "",
    )
    google_api_key: str = os.getenv(
        "GOOGLE_API_KEY",
        "",
    )
    semantic_scholar_api_key: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    pubmed_email: str = os.getenv("PUBMED_EMAIL", "hooke-bio@users.noreply.github.com")
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    app_port: int = int(os.getenv("APP_PORT", "8000"))


def _require_setting(name: str, value: str) -> str:
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def get_fast_client() -> "OpenAI":
    """OpenRouter client for cheap/fast orchestration calls."""
    from openai import OpenAI
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=_require_setting("OPENROUTER_API_KEY", settings.openrouter_api_key),
    )


def get_nebius_client() -> "OpenAI":
    """Nebius client for synthesis (DeepSeek-V3-fast, hackathon credits)."""
    from openai import OpenAI
    return OpenAI(
        base_url=settings.nebius_base_url,
        api_key=_require_setting("NEBIUS_API_KEY", settings.nebius_api_key),
        timeout=60,
    )


settings = Settings()
