"""Application configuration via environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    app_name: str = "AI Lead Reactivation Agent"
    debug: bool = False
    timezone: str = "Asia/Kuala_Lumpur"

    # Database / queue
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/reactivation"
    redis_url: str = "redis://localhost:6379/0"

    # Meta WhatsApp Cloud API
    graph_api_base: str = "https://graph.facebook.com/v21.0"
    meta_verify_token: str = "change-me-verify-token"
    meta_app_secret: str = ""  # used to validate X-Hub-Signature-256
    # Dev fallbacks; production uses per-tenant credentials in tenant_channels
    meta_access_token: str = ""
    meta_phone_number_id: str = ""

    # When true, outbound messages are logged + stored but never sent to Meta.
    whatsapp_dry_run: bool = True

    # LLM (Anthropic)
    anthropic_api_key: str = ""
    classifier_model: str = "claude-haiku-4-5-20251001"
    responder_model: str = "claude-sonnet-4-6"
    # When true (or no API key), deterministic heuristics replace API calls —
    # keeps dev/tests runnable with zero keys and zero cost.
    llm_dry_run: bool = True
    max_history_turns: int = 12

    # Admin dashboard auth
    admin_token: str = ""

    # Calendar (Cal.com)
    calcom_api_key: str = ""
    calcom_base_url: str = "https://api.cal.com/v2"
    calendar_dry_run: bool = True

    # Outbound throttle defaults (per tenant, enforced in M4; stored now for consistency)
    default_hourly_send_cap: int = 50
    quiet_hours_start: int = 21  # 9pm MYT
    quiet_hours_end: int = 9  # 9am MYT


@lru_cache
def get_settings() -> Settings:
    return Settings()
