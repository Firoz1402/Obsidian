from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: Literal["development", "staging", "testing", "production", "prod"] = "development"
    APP_LOG_LEVEL: str = "info"
    LOG_FORMAT: str = "console"
    HEALTH_PORT: int = 8100

    TEMPORAL_HOST: str = "temporal:7233"
    TEMPORAL_NAMESPACE: str = "obsidian"
    TEMPORAL_TLS_CERT_PATH: str = ""
    TEMPORAL_TLS_KEY_PATH: str = ""
    TEMPORAL_TASK_QUEUE_WORKFLOW: str = "obsidian-workflow"
    TEMPORAL_TASK_QUEUE_CPU: str = "obsidian-cpu"
    TEMPORAL_TASK_QUEUE_DB: str = "obsidian-db"

    WORKFLOW_MAX_CONCURRENT_RUNS: int = 100

    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_TRACE_SAMPLE_RATIO: float = 1.0
    OTEL_SERVICE_NAME: str = ""
    OTEL_SERVICE_NAME_BASE: str = "obsidian-workflow"
    OTEL_SERVICE_NAMESPACE: str = "obsidian"
    OTEL_SERVICE_INSTANCE_ID: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
