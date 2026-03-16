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
    # -----------------------------------------------------------------------
    # Nebius Token Factory — PRIMARY provider for all LLM calls
    # Three-tier model strategy benchmarked against available models:
    #   fast     → Qwen3-235B-Instruct  (1.1s)  classification, Mode1/2 synthesis
    #   analysis → DeepSeek-R1-0528-fast (3.8s)  Mode3 deep reasoning
    #   synthesis → DeepSeek-V3.2        (2.0s)  Mode3 brief generation
    # -----------------------------------------------------------------------
    nebius_api_key: str = os.getenv(
        "NEBIUS_API_KEY",
        "",
    )
    nebius_base_url: str = os.getenv(
        "NEBIUS_BASE_URL",
        "https://api.tokenfactory.nebius.com/v1/",
    )
    # Fast, cheap — query classification + genomic interpretation + Mode 1/2 synthesis
    nebius_fast_model: str = os.getenv(
        "NEBIUS_FAST_MODEL",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
    )
    # Reasoning — Mode 3 deep paper analysis (strips <think> tags)
    nebius_analysis_model: str = os.getenv(
        "NEBIUS_ANALYSIS_MODEL",
        "deepseek-ai/DeepSeek-R1-0528-fast",
    )
    # High-quality writing — Mode 3 final research brief
    nebius_synthesis_model: str = os.getenv(
        "NEBIUS_SYNTHESIS_MODEL",
        "deepseek-ai/DeepSeek-V3.2",
    )

    # -----------------------------------------------------------------------
    # OpenRouter — emergency fallback only (if Nebius errors/rate-limits)
    # -----------------------------------------------------------------------
    openrouter_api_key: str = os.getenv(
        "OPENROUTER_API_KEY",
        "",
    )
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
    )
    openrouter_fallback_model: str = os.getenv(
        "OPENROUTER_FALLBACK_MODEL",
        "google/gemini-2.5-flash",
    )

    # -----------------------------------------------------------------------
    # External APIs
    # -----------------------------------------------------------------------
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


def get_nebius_client() -> "OpenAI":
    """Primary Nebius Token Factory client — used for all LLM calls."""
    from openai import OpenAI
    return OpenAI(
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
        timeout=90,
    )


def get_openrouter_client() -> "OpenAI":
    """OpenRouter client — emergency fallback if Nebius unavailable."""
    from openai import OpenAI
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        timeout=60,
    )


# Back-compat alias used by genomic.py and other older callers
def get_fast_client() -> "OpenAI":
    """Alias for get_nebius_client (fast Qwen model handles fast calls)."""
    return get_nebius_client()


settings = Settings()
