from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 768  # Gemini text-embedding-004; schema column is vector(768)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://janawaaz:janawaaz@localhost:5433/janawaaz"

    # LLM (summaries + match verifier): Claude or Gemini — whichever key is set.
    # Claude is preferred when both are present. Embeddings are separate:
    # Anthropic has no embeddings endpoint, so vectors come from Gemini
    # text-embedding-004 (768-dim) or the dev fallback.
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-8"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    embeddings_provider: str = "gemini"  # "gemini" | "dev" (offline fallback, dev only)

    @property
    def llm_provider(self) -> str:
        if self.anthropic_api_key:
            return "claude"
        if self.gemini_api_key:
            return "gemini"
        return "none"

    sarvam_api_key: str = ""
    telegram_bot_token: str = ""
    render_api_key: str = ""

    # Voice alerts: Sarvam Bulbul TTS sent as Telegram audio, for low-literacy
    # users. Off by default to conserve API credits; enable for demos.
    voice_alerts: bool = False
    sarvam_tts_speaker: str = "anushka"

    # gemini-embedding-001 has a high similarity floor (~0.5 even for unrelated
    # same-domain text); 0.50 keeps the verifier working on plausible pairs only.
    similarity_threshold: float = 0.50
    # Hard cap on verifier calls per document — bounded LLM spend per sweep.
    max_gate_candidates: int = 20
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
