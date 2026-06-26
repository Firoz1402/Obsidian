from typing import List, Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings

# Environments where the app must never run with unset signing secrets.
_SECRET_REQUIRED_ENVS = {"staging", "production", "prod"}


class Settings(BaseSettings):
    APP_ENV: Literal["development", "staging", "testing", "production", "prod"]
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = False
    APP_LOG_LEVEL: str = "info"
    LOG_FORMAT: str = "console"
    USER_HASH_SECRET: str = ""
    APP_SECRET_KEY: str = ""
    CORS_ORIGINS: List[str] = ["*"]
    ACCESS_TOKEN_EXPIRY_HOURS: int = 1
    REFRESH_TOKEN_EXPIRY_HOURS: int = 720

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""
    DATABASE_URL: str = ""

    FILEBASE_ENDPOINT: str = "https://s3.filebase.io"
    FILEBASE_ACCESS_KEY_ID: str = ""
    FILEBASE_SECRET_ACCESS_KEY: str = ""
    FILEBASE_REGION: str = "auto"
    FILEBASE_BUCKET: str = "obsidian"

    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "obsidian"
    TEMPORAL_TLS_CERT_PATH: str = ""
    TEMPORAL_TLS_KEY_PATH: str = ""
    TEMPORAL_TASK_QUEUE_WORKFLOW: str = "obsidian-workflow"
    TEMPORAL_TASK_QUEUE_GPU: str = "obsidian-gpu"
    TEMPORAL_TASK_QUEUE_CPU: str = "obsidian-cpu"
    TEMPORAL_TASK_QUEUE_DB: str = "obsidian-db"

    INVESTIGATION_EVENT_STREAM_TTL_SECONDS: int = 86400

    REDIS_URL: str = ""
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_USERNAME: str = ""
    REDIS_PASSWORD: str = ""
    REDIS_TLS_ENABLED: bool = True
    REDIS_MAX_CONNECTIONS: int = 10

    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_TRACES_HEADERS: str = ""
    OTEL_EXPORTER_OTLP_METRICS_HEADERS: str = ""
    OTEL_EXPORTER_OTLP_LOGS_HEADERS: str = ""
    OTEL_TRACE_SAMPLE_RATIO: float = 1.0
    # Identity used for OTel resource attributes. service.name is the primary
    # axis Grafana groups by; setting OTEL_SERVICE_NAME differentiates dev vs
    # prod deployments even when they push to the same Grafana Cloud stack.
    # When unset, falls back to "{OTEL_SERVICE_NAME_BASE}-{APP_ENV}".
    OTEL_SERVICE_NAME: str = ""
    OTEL_SERVICE_NAME_BASE: str = "obsidian-api"
    OTEL_SERVICE_NAMESPACE: str = "obsidian"
    OTEL_SERVICE_INSTANCE_ID: str = ""
    BODY_LOG_MAX_BYTES: int = 4096
    BODY_LOG_SKIP_PATH_PREFIXES: List[str] = [
        "/auth",
        "/uploads",
    ]

    FIREBASE_CREDENTIALS_JSON: str = ""
    FIREBASE_WEB_API_KEY: str = ""

    AVATAR_UPLOAD_URL_TTL_MINUTES: int = 15
    AVATAR_MAX_SIZE_MB: int = 5
    AVATAR_ALLOWED_CONTENT_TYPES: str = "image/jpeg,image/png,image/webp"

    DOCS_USERNAME: str = "admin"
    DOCS_PASSWORD: str = ""

    @model_validator(mode="after")
    def _require_signing_secrets(self) -> "Settings":
        if self.APP_ENV in _SECRET_REQUIRED_ENVS:
            missing = [
                name
                for name in ("APP_SECRET_KEY", "USER_HASH_SECRET")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} must be set when APP_ENV={self.APP_ENV}."
                )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
