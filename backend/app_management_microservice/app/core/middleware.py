import json
import time
import traceback
import uuid
from typing import Any, Callable, Optional

import structlog
from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings
from app.core.exceptions import AppException
from app.core.responses import error_response
from app.utils.logging import get_logger
from app.utils.redaction import clip, redact

logger = get_logger(__name__)

_DEV_ENVS = {"DEV", "TEST", "STAGING", "DEVELOPMENT"}
_BODY_SAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_TEXT_CONTENT_TYPES = ("application/json", "application/x-www-form-urlencoded", "text/")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        span = trace.get_current_span()
        trace_id, span_id = _trace_ids(span)
        if trace_id:
            request.state.trace_id = trace_id
            request.state.span_id = span_id
            structlog.contextvars.bind_contextvars(trace_id=trace_id, span_id=span_id)
        if span is not None and span.is_recording():
            span.set_attribute("http.request_id", request_id)

        request_body = await _capture_request_body(request)

        log = logger.bind(request_id=request_id)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()

        log.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query_params=redact(dict(request.query_params)),
            client_ip=request.client.host if request.client else None,
            request_body=request_body,
            trace_id=trace_id,
            span_id=span_id,
        )

        response: Optional[Response] = None
        error_name: Optional[str] = None
        try:
            response = await call_next(request)
        except Exception as exc:
            error_name = type(exc).__name__
            log.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                route=_route_template(request),
                exception=error_name,
                exception_message=str(exc),
                duration_ms=_elapsed_ms(wall_start),
                cpu_ms=_elapsed_ms(cpu_start, cpu=True),
                hashed_user_uuid=getattr(request.state, "hashed_user_uuid", None),
                trace_id=trace_id,
                span_id=span_id,
            )
            raise
        finally:
            duration_ms = _elapsed_ms(wall_start)
            cpu_ms = _elapsed_ms(cpu_start, cpu=True)
            route = _route_template(request)
            if response is not None:
                status_code = response.status_code
            else:
                status_code = getattr(request.state, "final_status_code", 500)
            response_size = _response_size(response)
            hashed_user_uuid = getattr(request.state, "hashed_user_uuid", None)

            if response is not None:
                response.headers["X-Request-ID"] = request_id
                finish_log = log.error if status_code >= 500 else (
                    log.warning if status_code >= 400 else log.info
                )
                finish_log(
                    "request_finished",
                    method=request.method,
                    path=request.url.path,
                    route=route,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    cpu_ms=cpu_ms,
                    response_size_bytes=response_size,
                    hashed_user_uuid=hashed_user_uuid,
                    trace_id=trace_id,
                    span_id=span_id,
                )

            _record_metrics(
                method=request.method,
                route=route,
                status_code=status_code,
                duration_ms=duration_ms,
                cpu_ms=cpu_ms,
                response_size=response_size,
                error=error_name,
            )

            if span is not None and span.is_recording():
                if route:
                    span.set_attribute("http.route", route)
                span.set_attribute("http.response.body.size", response_size or 0)
                span.set_attribute("http.cpu_ms", cpu_ms)

            structlog.contextvars.clear_contextvars()

        return response


class GlobalErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            return self._handle(request, exc)

    def _handle(self, request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        hashed_user_uuid = getattr(request.state, "hashed_user_uuid", None)
        trace_id = getattr(request.state, "trace_id", None)
        span_id = getattr(request.state, "span_id", None)
        log = logger.bind(request_id=request_id)

        status_code = 500
        code = "INTERNAL_SERVER_ERROR"
        message = "An unexpected error occurred."
        details = None
        unhandled = False

        if isinstance(exc, AppException):
            status_code, code, message, details = (
                exc.status_code,
                exc.code,
                exc.message,
                exc.details,
            )
        elif isinstance(exc, RequestValidationError):
            status_code, code, message, details = (
                422,
                "VALIDATION_ERROR",
                "Request validation failed.",
                exc.errors(),
            )
        elif isinstance(exc, HTTPException):
            status_code, code, message = exc.status_code, "HTTP_ERROR", exc.detail
        else:
            unhandled = True
            if settings.APP_ENV.upper() in _DEV_ENVS:
                message = str(exc)
                details = {
                    "exception_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                }

        log_fn = log.exception if unhandled else (
            log.error if status_code >= 500 else log.warning
        )
        log_fn(
            "request_error",
            method=request.method,
            path=request.url.path,
            route=_route_template(request),
            status_code=status_code,
            error_code=code,
            error_message=message,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            hashed_user_uuid=hashed_user_uuid,
            trace_id=trace_id,
            span_id=span_id,
        )

        if status_code == 500 and settings.APP_ENV.upper() not in _DEV_ENVS:
            message = "Internal Server Error"
            details = None

        request.state.final_status_code = status_code
        return JSONResponse(
            status_code=status_code,
            content=error_response(
                code=code,
                message=message,
                details=details,
                request_id=request_id,
            ),
        )


async def _capture_request_body(request: Request) -> Any:
    if request.method not in _BODY_SAFE_METHODS:
        return None
    if _body_logging_disabled_for(request.url.path):
        return "[redacted: path skipped]"

    content_type = (request.headers.get("content-type") or "").lower()
    if not any(ct in content_type for ct in _TEXT_CONTENT_TYPES):
        return f"[non-text body: {content_type or 'unknown'}]"

    try:
        raw = await request.body()
    except Exception:
        return "[unreadable body]"

    if not raw:
        return None

    text = clip(raw.decode("utf-8", errors="replace"), settings.BODY_LOG_MAX_BYTES)
    if "json" in content_type:
        try:
            return redact(json.loads(text))
        except json.JSONDecodeError:
            return text
    return text


def _body_logging_disabled_for(path: str) -> bool:
    return any(path.startswith(p) for p in settings.BODY_LOG_SKIP_PATH_PREFIXES)


def _route_template(request: Request) -> Optional[str]:
    route = request.scope.get("route")
    return getattr(route, "path", None) if route is not None else None


def _trace_ids(span) -> tuple[Optional[str], Optional[str]]:
    if span is None:
        return None, None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def _response_size(response: Optional[Response]) -> int:
    if response is None:
        return 0
    cl = response.headers.get("content-length")
    if cl and cl.isdigit():
        return int(cl)
    body = getattr(response, "body", None)
    return len(body) if isinstance(body, (bytes, bytearray)) else 0


def _elapsed_ms(started_at: float, *, cpu: bool = False) -> float:
    now = time.process_time() if cpu else time.perf_counter()
    return round((now - started_at) * 1000.0, 3)


def _record_metrics(
    *,
    method: str,
    route: Optional[str],
    status_code: int,
    duration_ms: float,
    cpu_ms: float,
    response_size: int,
    error: Optional[str],
) -> None:
    from app.config.observability import observability_proxy

    observability_proxy.record_request(
        method=method,
        route=route,
        status_code=status_code,
        duration_ms=duration_ms,
        cpu_ms=cpu_ms,
        response_size=response_size,
        error=error,
    )
