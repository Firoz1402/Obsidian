import asyncio
import hashlib
import hmac
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Callable, Iterator, Optional

import structlog
from opentelemetry import trace

from app.config.settings import settings

_logger = structlog.get_logger("app.dependency")
_tracer = trace.get_tracer("app.dependency")


_HASH_FALLBACK_WARNED = False


def _hash_secret() -> bytes:
    global _HASH_FALLBACK_WARNED
    if settings.USER_HASH_SECRET:
        return settings.USER_HASH_SECRET.encode("utf-8")
    if not _HASH_FALLBACK_WARNED:
        logging.getLogger(__name__).warning(
            "user_hash_secret_missing falling_back_to_app_secret_key — "
            "set USER_HASH_SECRET to a permanent value before any prod traffic; "
            "rotating it later invalidates all historical user_hash values."
        )
        _HASH_FALLBACK_WARNED = True
    return settings.APP_SECRET_KEY.encode("utf-8")


def hash_user_id(user_id: str) -> str:
    """Stable, non-reversible 16-char hex tag for a user_id.

    Keyed by `USER_HASH_SECRET` (falls back to `APP_SECRET_KEY` with a warning).
    `USER_HASH_SECRET` must be set once and never rotated — rotation breaks
    every previously emitted hash, defeating the point of the tag.
    """
    if not user_id:
        return ""
    digest = hmac.new(
        _hash_secret(),
        user_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:16]


def set_login_email(email: Optional[str]) -> None:
    """Bind a login-attempt email to logs + the active span.

    Used on auth routes where there is no access token yet, so the request has
    no `hashed_user_uuid` to correlate by. Binding the submitted email lets us
    pivot from a 4xx auth failure to the user who tried.
    """
    if not email:
        return
    structlog.contextvars.bind_contextvars(login_email=email)
    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute("auth.login_email", email)


def set_login_attrs(
    *,
    device: Optional[str] = None,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
    if user_id:
        hashed_user_uuid = hash_user_id(user_id)
        if hashed_user_uuid:
            structlog.contextvars.bind_contextvars(hashed_user_uuid=hashed_user_uuid)
    if device:
        structlog.contextvars.bind_contextvars(device=device)

    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    if device is not None:
        span.set_attribute("auth.device", device)
    if user_id is not None:
        span.set_attribute("auth.user_id", user_id)
        span.set_attribute("auth.hashed_user_uuid", hash_user_id(user_id))
    if provider is not None:
        span.set_attribute("auth.provider", provider)


@asynccontextmanager
async def traced_call(
    kind: str,
    target: str,
    operation: str,
    *,
    record_metric: Optional[Callable[[float, dict], None]] = None,
    **extra_attrs,
) -> AsyncIterator[None]:
    """Trace + log + (optionally) measure a downstream dependency call.

    `kind`      — db | redis | storage | vector | http | external
    `target`    — logical name (e.g. "supabase.users", "redis", "supabase.storage")
    `operation` — short verb (e.g. "select_by_email", "setex", "upload")
    `record_metric(duration_ms, attrs)` — optional callback to push to a histogram.
    """
    span_name = f"{kind}.{target}.{operation}"
    attrs = {"dep.kind": kind, "dep.target": target, "dep.operation": operation, **extra_attrs}
    started_at = time.perf_counter()
    error: Optional[str] = None
    with _tracer.start_as_current_span(span_name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        try:
            yield
        except Exception as exc:
            error = type(exc).__name__
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, error))
            raise
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            span.set_attribute("dep.duration_ms", duration_ms)
            log_attrs = {**attrs, "duration_ms": round(duration_ms, 3)}
            if error:
                log_attrs["error"] = error
                _logger.warning("dependency_call_failed", **log_attrs)
            else:
                _logger.info("dependency_call", **log_attrs)
            if record_metric is not None:
                metric_attrs = {**attrs, "error": error or ""}
                try:
                    record_metric(duration_ms, metric_attrs)
                except Exception:  # never let metrics break the request
                    logging.getLogger(__name__).debug("dep_metric_record_failed", exc_info=True)


@contextmanager
def traced_call_sync(
    kind: str,
    target: str,
    operation: str,
    *,
    record_metric: Optional[Callable[[float, dict], None]] = None,
    **extra_attrs,
) -> Iterator[None]:
    """Synchronous variant of traced_call for blocking SDK calls."""
    span_name = f"{kind}.{target}.{operation}"
    attrs = {"dep.kind": kind, "dep.target": target, "dep.operation": operation, **extra_attrs}
    started_at = time.perf_counter()
    error: Optional[str] = None
    with _tracer.start_as_current_span(span_name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        try:
            yield
        except Exception as exc:
            error = type(exc).__name__
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, error))
            raise
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            span.set_attribute("dep.duration_ms", duration_ms)
            log_attrs = {**attrs, "duration_ms": round(duration_ms, 3)}
            if error:
                log_attrs["error"] = error
                _logger.warning("dependency_call_failed", **log_attrs)
            else:
                _logger.info("dependency_call", **log_attrs)
            if record_metric is not None:
                metric_attrs = {**attrs, "error": error or ""}
                try:
                    record_metric(duration_ms, metric_attrs)
                except Exception:
                    logging.getLogger(__name__).debug("dep_metric_record_failed", exc_info=True)


async def to_thread_traced(
    kind: str,
    target: str,
    operation: str,
    fn,
    /,
    *args,
    record_metric: Optional[Callable[[float, dict], None]] = None,
    **kwargs,
):
    """Run a blocking callable in a thread under traced_call, propagating context."""
    async with traced_call(kind, target, operation, record_metric=record_metric):
        return await asyncio.to_thread(fn, *args, **kwargs)
