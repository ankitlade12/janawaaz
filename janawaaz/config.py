from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 768  # Gemini text-embedding-004; schema column is vector(768)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://janawaaz:janawaaz@localhost:5433/janawaaz"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    embeddings_provider: str = "gemini"  # "gemini" | "dev" (offline fallback, dev only)

    sarvam_api_key: str = ""
    telegram_bot_token: str = ""
    render_api_key: str = ""

    # Voice alerts: Sarvam Bulbul TTS sent as Telegram audio, for low-literacy
    # users. Off by default to conserve API credits; enable for demos.
    voice_alerts: bool = False
    sarvam_tts_speaker: str = "anushka"

    similarity_threshold: float = 0.30
    # Tier 1 requires the LLM verifier to confirm AND return a span found verbatim
    # in the document text; similarity alone can never push past Tier 2.
    alert_languages: str = "hi,mr"

    http_timeout_seconds: float = 30.0
    user_agent: str = (
        "JanAwaazBot/0.1 (+https://github.com/ankitlade12/janawaaz; civic consultation alerts)"
    )


@lru_cache
def settings() -> Settings:
    return Settings()
