"""Application configuration loaded exclusively from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that appear in .env.example / documentation. The application refuses to
# boot in production if any secret still has one of these values.
PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "changeme",
    "replace-with-secure-random-value",
    "secret",
    "password",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    app_name: str = "TaskBoard"
    app_env: Literal["production", "development", "test"] = "production"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8080"
    # Origins permitted for WebSocket connections and cookie-authenticated requests.
    # Empty means "derive from PUBLIC_BASE_URL".
    allowed_origins: str = ""

    # Database
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "taskboard"
    postgres_user: str = "taskboard"
    postgres_password: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: SecretStr = SecretStr("")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_expire_days: int = Field(default=14, ge=1, le=90)
    password_reset_expire_minutes: int = Field(default=60, ge=5, le=1440)
    invitation_expire_days: int = Field(default=7, ge=1, le=60)
    # None (unset/empty) = automatic: Secure cookies when PUBLIC_BASE_URL is https.
    cookie_secure: bool | None = None
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 2

    # Brute-force protection
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900
    login_lockout_seconds: int = 900
    ip_auth_rate_per_minute: int = 30
    register_rate_per_minute: int = 10
    password_reset_rate_per_minute: int = 5

    # Attachments
    attachments_dir: str = "/data/attachments"
    max_upload_mb: int = Field(default=10, ge=1, le=100)

    # Email
    email_backend: Literal["console", "smtp"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = True
    smtp_use_tls: bool = False
    email_from: str = "TaskBoard <no-reply@taskboard.local>"

    # Realtime
    ws_auth_timeout_seconds: float = 5.0
    ws_replay_limit: int = 500
    presence_ttl_seconds: int = 45

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def _empty_is_auto(cls, v):
        return None if isinstance(v, str) and v.strip() == "" else v

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is None:
            return self.public_base_url.lower().startswith("https://")
        return self.cookie_secure

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _validate_secrets(self) -> Settings:
        if self.app_env == "production":
            problems = []
            secret = self.jwt_secret.get_secret_value()
            if secret.lower() in PLACEHOLDER_SECRETS or len(secret) < 32:
                problems.append("JWT_SECRET must be a random value of at least 32 characters")
            if self.postgres_password.get_secret_value().lower() in PLACEHOLDER_SECRETS:
                problems.append("POSTGRES_PASSWORD must be set to a non-placeholder value")
            if problems:
                raise ValueError(
                    "Insecure production configuration: "
                    + "; ".join(problems)
                    + ". Run ./scripts/generate-secrets.sh to create secure values."
                )
        elif len(self.jwt_secret.get_secret_value()) < 16:
            raise ValueError("JWT_SECRET must be at least 16 characters")
        return self

    @property
    def database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def origins(self) -> set[str]:
        if self.allowed_origins.strip():
            return {o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()}
        return {self.public_base_url.rstrip("/")}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # Print only the messages: the default repr would echo (truncated) input values.
        messages = "; ".join(str(e.get("msg", "")).removeprefix("Value error, ") for e in exc.errors())
        raise SystemExit(f"TaskBoard configuration error: {messages}") from None
