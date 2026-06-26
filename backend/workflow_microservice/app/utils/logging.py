import logging
import sys
from typing import Any, MutableMapping

import structlog
from opentelemetry import trace

from app.config.settings import settings


_NOISY = (
    "asyncio",
    "httpx",
    "httpcore",
    "urllib3",
    "watchfiles",
    "watchfiles.main",
)


def configure_logging() -> None:
    use_json = (settings.LOG_FORMAT or "").lower() == "json" or settings.APP_ENV != "development"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_otel_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=renderer,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        root_logger.removeHandler(existing)
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.APP_LOG_LEVEL.upper())

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def _inject_otel_context(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    span = trace.get_current_span()
    if span is None:
        return event_dict
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return event_dict
    event_dict["trace_id"] = format(ctx.trace_id, "032x")
    event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
