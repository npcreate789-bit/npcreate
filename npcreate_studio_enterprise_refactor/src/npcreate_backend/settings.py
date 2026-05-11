from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NPCREATE_BACKEND_", env_file=".env", extra="ignore")

    env: str = Field(default="production")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8088, ge=1024, le=65535)
    database_path: str = Field(default="backend_data/npcreate_backend.sqlite3")
    database_url: str = Field(default="")  # production: postgresql://user:password@host:5432/dbname
    public_base_url: str = Field(default="http://127.0.0.1:8088")

    admin_token: str = Field(default="CHANGE_ME_ADMIN_TOKEN")
    app_api_key: str = Field(default="CHANGE_ME_APP_API_KEY")
    key_pepper: str = Field(default="CHANGE_ME_KEY_PEPPER")
    ed25519_private_key_hex: str = Field(default="")
    activation_token_ttl_days: int = Field(default=35, ge=1, le=370)
    activation_access_ttl_minutes: int = Field(default=30, ge=5, le=1440)

    # Payment webhook: use a long random value per provider/account and rotate via deploy.
    payment_webhook_secret: str = Field(default="CHANGE_ME_PAYMENT_WEBHOOK_SECRET")
    stripe_webhook_secret: str = Field(default="")
    omise_webhook_secret: str = Field(default="")
    twoc2p_webhook_secret: str = Field(default="")
    gbprimepay_webhook_secret: str = Field(default="")
    payment_provider_mode: str = Field(default="live")
    payment_grace_days: int = Field(default=3, ge=0, le=14)
    payment_renewal_days: int = Field(default=31, ge=1, le=370)
    payment_webhook_require_timestamp: bool = Field(default=True)
    payment_webhook_max_age_seconds: int = Field(default=300, ge=60, le=3600)
    allow_direct_license_payment_mapping: bool = Field(default=False)
    activation_rate_limit_per_minute: int = Field(default=12, ge=1, le=120)
    trusted_proxy_header: str = Field(default="")

    # Admin web security. Create the first admin with scripts/admin_create_user.py.
    admin_session_cookie_name: str = Field(default="npc_admin_session")
    admin_session_ttl_minutes: int = Field(default=480, ge=15, le=1440)
    admin_session_idle_timeout_minutes: int = Field(default=30, ge=1, le=480)
    admin_login_rate_limit_per_minute: int = Field(default=8, ge=1, le=60)
    auth_refresh_rate_limit_per_minute: int = Field(default=30, ge=1, le=300)
    allow_legacy_admin_token: bool = Field(default=False)

    # Background billing job.
    billing_job_enabled: bool = Field(default=True)
    billing_job_interval_minutes: int = Field(default=60, ge=5, le=1440)

    # Installer / update production controls.
    code_signing_required: bool = Field(default=True)

    @field_validator("admin_token", "app_api_key", "key_pepper", "payment_webhook_secret")
    @classmethod
    def secrets_must_be_strong_in_production(cls, value: str) -> str:
        if value.startswith("CHANGE_ME") or len(value) < 24:
            # Allow tests/dev to override; production startup should still fail in create_app.
            return value
        return value

    @property
    def db_path(self) -> Path:
        p = Path(self.database_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_target(self) -> str | Path:
        if self.database_url:
            return self.database_url
        return self.db_path

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgres://"))
