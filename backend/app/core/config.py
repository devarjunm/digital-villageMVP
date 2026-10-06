"""Application settings.

Every value is read from the environment (see .env.example). Nothing in the
codebase reads os.environ directly for configuration, so the full runtime
configuration is auditable from one place.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]  # .../digital-village


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ core
    app_name: str = "Digital Village"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"
    cors_origins: str = "http://localhost:3000,http://localhost:8081"

    # -------------------------------------------------------------- security
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_length: int = 6
    sms_provider: Literal["console", "sms_gateway"] = "console"
    rate_limit_enabled: bool = True
    password_min_length: int = 8
    login_max_failures: int = 8
    login_lockout_minutes: int = 15

    # -------------------------------------------------------------- database
    database_url: str = "postgresql+psycopg://dv:dv_password@localhost:5432/digital_village"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False
    db_pool_pre_ping: bool = True

    # ----------------------------------------------------------------- redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_weather_seconds: int = 900
    cache_ttl_market_seconds: int = 900
    job_queue_mode: Literal["auto", "redis", "inline"] = "auto"

    # ----------------------------------------------------------- object store
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = str(REPO_ROOT / "data" / "uploads")
    storage_public_base_url: str = "http://localhost:8000/files"
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    max_upload_mb: int = 8
    image_min_side_px: int = 64
    image_max_side_px: int = 8000

    # -------------------------------------------------------- notifications
    push_provider: Literal["console", "fcm"] = "console"
    push_credentials_file: str = ""
    notification_digest_hour: int = 6
    notification_max_per_day: int = 20

    # --------------------------------------------------------------- weather
    weather_provider: Literal["mock", "openweathermap"] = "mock"
    weather_api_key: str = ""
    weather_api_base_url: str = "https://api.openweathermap.org/data/2.5"

    # ---------------------------------------------------------------- market
    market_provider: Literal["mock", "data_gov_in", "agmarknet"] = "mock"
    market_api_key: str = ""
    market_api_base_url: str = ""
    market_resource_id: str = ""

    # ------------------------------------------------------------------- LLM
    llm_provider: Literal["mock", "openai", "anthropic", "ollama", "custom"] = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 30
    llm_max_output_tokens: int = 800
    llm_temperature: float = 0.2

    # ------------------------------------------------------------ embeddings
    embedding_provider: Literal["mock", "openai", "sentence_transformers", "custom"] = "mock"
    embedding_api_key: str = ""
    embedding_model: str = "mock-hash-embedding-v1"
    embedding_dim: int = 384
    embedding_version: str = "1"

    # -------------------------------------------------------------------- ML
    ml_models_dir: str = str(REPO_ROOT / "artifacts" / "models")
    mlflow_tracking_uri: str = ""
    mlflow_registry_uri: str = ""
    mlflow_experiment_crop_recommendation: str = "crop-recommendation"
    mlflow_experiment_disease_detection: str = "disease-detection"
    mlflow_experiment_yield_prediction: str = "yield-prediction"
    mlflow_experiment_price_prediction: str = "price-prediction"
    ml_disease_model_version: str = ""
    ml_crop_rec_model_version: str = ""
    ml_yield_model_version: str = ""
    ml_price_model_version: str = ""
    disease_top_k: int = 5
    rag_top_k: int = 6
    rag_min_score: float = 0.15
    # Optional cross-encoder reranker (empty ⇒ deterministic lexical reranker)
    reranker_model: str = ""
    rag_chunk_chars: int = 900
    rag_chunk_overlap_chars: int = 150

    # ------------------------------------------------------------- analytics
    analytics_enabled: bool = True
    # When true (default), product events for a *signed-in* user are only recorded
    # if the user has granted the ANALYTICS consent purpose. Anonymous/aggregate
    # server metrics are unaffected. Set to false only in development if you need
    # event volume before the consent screen is built.
    analytics_requires_consent: bool = True
    # Version of the consent/privacy text that recorded decisions refer to.
    # Bumping it makes every existing decision "outdated", so clients ask again.
    consent_policy_version: str = "2026-10-01"
    product_event_allowlist: str = (
        "app_opened,post_created,post_viewed,comment_created,ai_request,disease_scan,"
        "recommendation_viewed,scheme_viewed,search_performed,notification_interaction,"
        "market_viewed,weather_viewed,profile_updated,farm_created,crop_created,"
        "assistant_message,agent_run,feedback_submitted"
    )

    # ------------------------------------------------------------------ seed
    allow_prod_seed: bool = False
    demo_user_password: str = "DemoPass!23"

    # ------------------------------------------------------------ validators
    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("jwt_secret")
    @classmethod
    def _secret_strength(cls, v: str, info) -> str:
        env = (info.data or {}).get("app_env", "development")
        if env == "production" and (len(v) < 32 or "change-me" in v or v.startswith("dev-only")):
            raise ValueError(
                "JWT_SECRET must be a random value of at least 32 characters in production"
            )
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        if self.app_env == "production":
            if not self.cors_origins or self.cors_origins.strip() == "*":
                raise ValueError("CORS_ORIGINS must list explicit origins in production")
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false in production")
        return self

    # ------------------------------------------------------------- shortcuts
    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in ("", "*"):
            return ["*"] if self.app_env != "production" else []
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def analytics_event_names(self) -> set[str]:
        return {e.strip() for e in self.product_event_allowlist.split(",") if e.strip()}

    @property
    def demo_mode(self) -> bool:
        """True when every external dependency is served by a local provider."""
        return (
            self.weather_provider == "mock"
            and self.market_provider == "mock"
            and self.llm_provider == "mock"
            and self.embedding_provider == "mock"
        )

    def resolve_dir(self, value: str) -> Path:
        """Resolve a configured directory to an absolute path.

        Relative values (e.g. `ML_MODELS_DIR=./artifacts/models`) are anchored at
        the repository root, never at the process working directory, so the API,
        worker, Alembic and scripts all see the same artefacts regardless of where
        they were started from.
        """
        path = Path(value).expanduser()
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def models_path(self) -> Path:
        return self.resolve_dir(self.ml_models_dir)

    @property
    def storage_dir(self) -> Path:
        return self.resolve_dir(self.storage_local_dir)

    def provider_status(self) -> dict[str, dict[str, object]]:
        """Machine-readable provenance of the active providers (used by /ready
        and the admin system panel, so operators can see at a glance that e.g.
        weather is still the demo provider)."""
        return {
            "weather": {
                "provider": self.weather_provider,
                "is_demo": self.weather_provider == "mock",
            },
            "market": {"provider": self.market_provider, "is_demo": self.market_provider == "mock"},
            "llm": {"provider": self.llm_provider, "is_demo": self.llm_provider == "mock"},
            "embeddings": {
                "provider": self.embedding_provider,
                "is_demo": self.embedding_provider == "mock",
                "model": self.embedding_model,
                "dim": self.embedding_dim,
            },
            "storage": {
                "provider": self.storage_backend,
                "is_demo": self.storage_backend == "local",
            },
            "sms": {"provider": self.sms_provider, "is_demo": self.sms_provider == "console"},
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that need to re-read the environment."""
    get_settings.cache_clear()


settings = get_settings()

# Ensure the local directories we write to exist. Done here (not at import of a
# service) so that `python -c "import app.core.config"` is side-effect safe.
for _p in (settings.storage_local_dir, settings.ml_models_dir):
    if not os.path.isabs(_p):
        _p = str(REPO_ROOT / _p)
    Path(_p).mkdir(parents=True, exist_ok=True)
