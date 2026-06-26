import logging
from typing import Optional
from urllib.parse import unquote

from fastapi import FastAPI
from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_ON,
    ParentBased,
    TraceIdRatioBased,
)
from opentelemetry.semconv.resource import ResourceAttributes

from app.config.settings import settings

logger = logging.getLogger(__name__)

SERVICE_VERSION = "1.0.0"


def _resolve_service_name() -> str:
    explicit = (settings.OTEL_SERVICE_NAME or "").strip()
    if explicit:
        return explicit
    base = (settings.OTEL_SERVICE_NAME_BASE or "obsidian-api").strip()
    env = (settings.APP_ENV or "unknown").strip().lower()
    return f"{base}-{env}"


SERVICE_NAME = _resolve_service_name()
HEALTH_EXCLUDED_URLS = "metrics"
METRIC_EXPORT_INTERVAL_MILLIS = 60_000

# Structlog kwargs that should surface as first-class OTel log attributes
# (and therefore as filterable columns in Grafana's table view) instead of
# being buried in the rendered JSON message body.
_LIFTED_LOG_ATTRS = (
    "event",
    "method",
    "path",
    "route",
    "status_code",
    "duration_ms",
    "cpu_ms",
    "response_size_bytes",
    "hashed_user_uuid",
    "login_email",
    "request_id",
    "trace_id",
    "span_id",
    "error_code",
    "error_message",
    "exception",
    "exception_type",
    "exception_message",
    "client_ip",
)


class _StructlogAwareLoggingHandler(LoggingHandler):
    """OTel logging handler that lifts whitelisted structlog event_dict
    fields onto the LogRecord so they become OTel log attributes."""

    def emit(self, record: logging.LogRecord) -> None:
        event_dict = getattr(record, "_record", None)
        if isinstance(event_dict, dict):
            for key in _LIFTED_LOG_ATTRS:
                value = event_dict.get(key)
                if value is None:
                    continue
                if not hasattr(record, key):
                    setattr(record, key, value)
        super().emit(record)


class ObservabilityProxy:
    def __init__(self) -> None:
        self.tracer_provider: Optional[TracerProvider] = None
        self.meter_provider: Optional[MeterProvider] = None
        self.logger_provider: Optional[LoggerProvider] = None
        self.otel_logging_handler: Optional[LoggingHandler] = None
        self.prometheus_reader: Optional[PrometheusMetricReader] = None
        self.request_duration_ms: Optional[Histogram] = None
        self.request_cpu_ms: Optional[Histogram] = None
        self.response_size_bytes: Optional[Histogram] = None
        self.requests_total: Optional[Counter] = None
        self.dependency_duration_ms: Optional[Histogram] = None
        self.dependency_calls_total: Optional[Counter] = None
        self.dependency_up: Optional[metrics.Gauge] = None
        self._httpx_instrumented = False
        self._fastapi_instrumented = False
        self._redis_instrumented = False

    def init_clients(self) -> None:
        resource_attrs = {
            ResourceAttributes.SERVICE_NAME: SERVICE_NAME,
            ResourceAttributes.SERVICE_VERSION: SERVICE_VERSION,
            ResourceAttributes.SERVICE_NAMESPACE: settings.OTEL_SERVICE_NAMESPACE or "obsidian",
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.APP_ENV,
        }
        if settings.OTEL_SERVICE_INSTANCE_ID:
            resource_attrs[ResourceAttributes.SERVICE_INSTANCE_ID] = settings.OTEL_SERVICE_INSTANCE_ID
        resource = Resource.create(resource_attrs)
        logger.info(
            "observability_resource_initialized service.name=%s namespace=%s env=%s",
            SERVICE_NAME, resource_attrs[ResourceAttributes.SERVICE_NAMESPACE], settings.APP_ENV,
        )

        traces_endpoint = _signal_endpoint("traces", "/v1/traces")
        metrics_endpoint = _signal_endpoint("metrics", "/v1/metrics")
        logs_endpoint = _signal_endpoint("logs", "/v1/logs")

        self._init_metrics(resource, _signal_headers("metrics"), metrics_endpoint)
        self._init_app_metrics()

        if traces_endpoint:
            self._init_traces(resource, _signal_headers("traces"), traces_endpoint)
            self._init_httpx_instrumentation()
            self._init_redis_instrumentation()
        else:
            logger.info("observability_traces_otlp_disabled_no_endpoint")

        if logs_endpoint:
            self._init_logs(resource, _signal_headers("logs"), logs_endpoint)
        else:
            logger.info("observability_logs_otlp_disabled_no_endpoint")

        self._init_system_instrumentation()

    def instrument_fastapi(self, app: FastAPI) -> None:
        if self._fastapi_instrumented:
            return
        if self.tracer_provider is None and self.meter_provider is None:
            return
        try:
            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=self.tracer_provider,
                meter_provider=self.meter_provider,
                excluded_urls=HEALTH_EXCLUDED_URLS,
                server_request_hook=_server_request_hook,
                client_request_hook=_client_request_hook,
                client_response_hook=_client_response_hook,
            )
            self._fastapi_instrumented = True
            logger.info("observability_fastapi_instrumented")
        except Exception as e:
            logger.warning("observability_fastapi_instrumentation_failed: %s", e)

    def get_tracer(self, name: str) -> trace.Tracer:
        return trace.get_tracer(name, SERVICE_VERSION, self.tracer_provider)

    def get_meter(self, name: str) -> metrics.Meter:
        return metrics.get_meter(name, SERVICE_VERSION, self.meter_provider)

    async def close_clients(self) -> None:
        if self.tracer_provider:
            self.tracer_provider.shutdown()
        if self.meter_provider:
            self.meter_provider.shutdown()
        if self.logger_provider:
            self.logger_provider.shutdown()

    def _init_traces(self, resource: Resource, headers: Optional[dict], endpoint: str) -> None:
        try:
            sampler = _build_sampler()
            self.tracer_provider = TracerProvider(resource=resource, sampler=sampler)
            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                headers=headers,
            )
            self.tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(self.tracer_provider)
            logger.info(
                "observability_traces_initialized sampler=%s", sampler.get_description()
            )
        except Exception as e:
            self.tracer_provider = None
            logger.error("observability_traces_failed: %s", e)

    def _init_metrics(
        self, resource: Resource, headers: Optional[dict], endpoint: Optional[str]
    ) -> None:
        try:
            readers: list[MetricReader] = []

            self.prometheus_reader = PrometheusMetricReader()
            readers.append(self.prometheus_reader)

            if endpoint:
                exporter = OTLPMetricExporter(
                    endpoint=endpoint,
                    headers=headers,
                )
                readers.append(
                    PeriodicExportingMetricReader(
                        exporter,
                        export_interval_millis=METRIC_EXPORT_INTERVAL_MILLIS,
                    )
                )

            self.meter_provider = MeterProvider(resource=resource, metric_readers=readers)
            metrics.set_meter_provider(self.meter_provider)
            logger.info(
                "observability_metrics_initialized otlp=%s", "on" if endpoint else "off"
            )
        except Exception as e:
            self.meter_provider = None
            self.prometheus_reader = None
            logger.error("observability_metrics_failed: %s", e)

    def _init_logs(self, resource: Resource, headers: Optional[dict], endpoint: str) -> None:
        try:
            self.logger_provider = LoggerProvider(resource=resource)
            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers=headers,
            )
            self.logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            _logs.set_logger_provider(self.logger_provider)

            self.otel_logging_handler = _StructlogAwareLoggingHandler(
                level=logging.INFO,
                logger_provider=self.logger_provider,
            )
            logging.getLogger().addHandler(self.otel_logging_handler)
            logger.info("observability_logs_initialized")
        except Exception as e:
            self.logger_provider = None
            self.otel_logging_handler = None
            logger.error("observability_logs_failed: %s", e)

    def _init_httpx_instrumentation(self) -> None:
        if self._httpx_instrumented:
            return
        try:
            HTTPXClientInstrumentor().instrument(
                tracer_provider=self.tracer_provider,
                meter_provider=self.meter_provider,
            )
            self._httpx_instrumented = True
        except Exception as e:
            logger.warning("observability_httpx_instrumentation_failed: %s", e)

    def _init_redis_instrumentation(self) -> None:
        if self._redis_instrumented:
            return
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor
        except ImportError:
            logger.info("observability_redis_instrumentation_unavailable")
            return
        try:
            RedisInstrumentor().instrument(tracer_provider=self.tracer_provider)
            self._redis_instrumented = True
            logger.info("observability_redis_instrumented")
        except Exception as e:
            logger.warning("observability_redis_instrumentation_failed: %s", e)

    def _init_system_instrumentation(self) -> None:
        # Intentionally disabled: SystemMetricsInstrumentor emits hundreds of high-cardinality series 
        # and exceeds the Grafana Cloud free-tier 10k active-series cap, causing data loss.
        pass

    def _init_app_metrics(self) -> None:
        if self.meter_provider is None:
            return
        meter = metrics.get_meter("app.http", SERVICE_VERSION, self.meter_provider)
        self.request_duration_ms = meter.create_histogram(
            name="app.http.server.request.duration",
            unit="ms",
            description="End-to-end HTTP server request latency.",
        )
        self.request_cpu_ms = meter.create_histogram(
            name="app.http.server.request.cpu",
            unit="ms",
            description="CPU time consumed by an HTTP request handler.",
        )
        self.response_size_bytes = meter.create_histogram(
            name="app.http.server.response.body.size",
            unit="By",
            description="HTTP response body size in bytes.",
        )
        self.requests_total = meter.create_counter(
            name="app.http.requests",
            description="HTTP requests served, labeled by method/route/status_code/status_class/error.",
        )
        self.dependency_duration_ms = meter.create_histogram(
            name="app.dependency.duration",
            unit="ms",
            description="Latency of downstream dependency calls (db, redis, storage, ...).",
        )
        self.dependency_calls_total = meter.create_counter(
            name="app.dependency.calls",
            description="Dependency calls attempted, labeled by kind/target/operation/status/error.",
        )
        try:
            self.dependency_up = meter.create_gauge(
                name="app.dependency.up",
                description="1 if dependency is healthy, 0 otherwise.",
            )
        except AttributeError:
            pass # fallback if gauge not available in older OTel version

    def record_request(
        self,
        *,
        method: str,
        route: Optional[str],
        status_code: int,
        duration_ms: float,
        cpu_ms: float,
        response_size: int,
        error: Optional[str],
    ) -> None:
        status_class = _status_class(status_code)
        attrs = {
            "http.method": method,
            "http.route": route or "unmatched",
            "http.status_code": str(status_code),
            "http.status_class": status_class,
            "error": error or "",
        }
        clean = _clean_attrs(attrs)
        if self.request_duration_ms is not None:
            self.request_duration_ms.record(duration_ms, attributes=clean)
        if self.request_cpu_ms is not None:
            self.request_cpu_ms.record(cpu_ms, attributes=clean)
        if self.response_size_bytes is not None:
            self.response_size_bytes.record(response_size, attributes=clean)
        if self.requests_total is not None:
            self.requests_total.add(1, attributes=clean)

    def record_dependency(self, duration_ms: float, attrs: dict) -> None:
        if self.dependency_duration_ms is None and self.dependency_calls_total is None:
            return
        error = attrs.get("error") or ""
        normalized = {**attrs, "error": error, "status": "error" if error else "ok"}
        clean = _clean_attrs(normalized)
        if self.dependency_duration_ms is not None:
            self.dependency_duration_ms.record(duration_ms, attributes=clean)
        if self.dependency_calls_total is not None:
            self.dependency_calls_total.add(1, attributes=clean)


def _build_sampler():
    if settings.APP_ENV.lower() in {"development", "dev", "test"}:
        return ALWAYS_ON
    ratio = max(0.0, min(1.0, settings.OTEL_TRACE_SAMPLE_RATIO))
    return ParentBased(root=TraceIdRatioBased(ratio))


def _clean_attrs(attrs: dict) -> dict:
    return {k: v for k, v in attrs.items() if v is not None and not isinstance(v, (dict, list))}


def _status_class(status_code: int) -> str:
    if status_code < 100 or status_code >= 600:
        return "unknown"
    return f"{status_code // 100}xx"


def _server_request_hook(span, scope) -> None:
    if span is None or not span.is_recording():
        return
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", []) or []
    }
    request_id = headers.get("x-request-id")
    if request_id:
        span.set_attribute("http.request_id", request_id)
    user_agent = headers.get("user-agent")
    if user_agent:
        span.set_attribute("http.user_agent", user_agent)
    client = scope.get("client")
    if client:
        span.set_attribute("http.client_ip", client[0])


def _client_request_hook(span, scope, message) -> None:
    return None


def _client_response_hook(span, scope, message) -> None:
    return None


def _signal_endpoint(signal_type: str, default_path: str) -> Optional[str]:
    specific_endpoint = getattr(settings, f"OTEL_EXPORTER_OTLP_{signal_type.upper()}_ENDPOINT", None)
    if specific_endpoint:
        return specific_endpoint.strip()
    
    base = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip().rstrip("/")
    if not base:
        return None
    return base if base.endswith(default_path) else f"{base}{default_path}"


def _signal_headers(signal_type: str) -> Optional[dict]:
    specific_headers = getattr(settings, f"OTEL_EXPORTER_OTLP_{signal_type.upper()}_HEADERS", None)
    if specific_headers:
        return _parse_headers(specific_headers)
    
    base_headers = settings.OTEL_EXPORTER_OTLP_HEADERS
    return _parse_headers(base_headers) if base_headers else None


def _parse_headers(raw: str) -> Optional[dict]:
    if not raw:
        return None
    parsed = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        parsed[key.strip()] = unquote(value.strip())
    return parsed or None


observability_proxy = ObservabilityProxy()
