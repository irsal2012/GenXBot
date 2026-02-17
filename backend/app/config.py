"""Application settings for GenXBot backend."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "GenXBot"
    environment: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    auto_approve_safe_actions: bool = False
    max_steps_per_run: int = 10
    action_retry_attempts: int = 2
    action_retry_backoff_seconds: float = 0.2
    openai_api_key: Optional[str] = None
    queue_worker_enabled: bool = True
    run_store_backend: str = "sqlite"
    run_store_path: str = ".genxai/genxbot_runs.sqlite3"
    sandbox_enabled: bool = True
    sandbox_root: str = ".genxai/sandboxes"

    memory_persistence_enabled: bool = True
    memory_persistence_backend: str = "sqlite"
    memory_persistence_path: str = ".genxai/memory/genxbot"
    memory_sqlite_path: str = ".genxai/memory/genxbot/memory.db"

    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379"

    graph_enabled: bool = False
    graph_backend: str = "neo4j"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    channel_webhook_security_enabled: bool = False
    slack_signing_secret: str = ""
    telegram_webhook_secret: str = ""
    slack_signing_secrets: str = ""
    telegram_webhook_secrets: str = ""
    webhook_replay_window_seconds: int = 300

    channel_state_backend: str = "sqlite"
    channel_state_sqlite_path: str = ".genxai/genxbot_channel_state.sqlite3"

    channel_outbound_enabled: bool = False
    slack_outbound_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_api_base_url: str = "https://api.telegram.org"
    channel_outbound_retry_worker_enabled: bool = True
    channel_outbound_retry_max_attempts: int = 3
    channel_outbound_retry_backoff_seconds: float = 0.2

    channel_command_approver_allowlist: str = ""
    channel_idempotency_cache_ttl_seconds: int = 900
    channel_idempotency_cache_max_entries: int = 1000
    admin_audit_max_entries: int = 5000
    admin_api_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
