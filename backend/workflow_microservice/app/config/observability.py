from urllib.parse import unquote

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased
from opentelemetry.semconv.resource import ResourceAttributes

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

SERVICE_VERSION = "1.0.0"


def _resolve_service_name() -> str:
    explicit = (settings.OTEL_SERVICE_NAME or "").strip()
    if explicit:
        return explicit
    base = (settings.OTEL_SERVICE_NAME_BASE or "obsidian-workflow").strip()
    env = (settings.APP_ENV or "unknown").strip().lower()
    return f"{base}-{env}"


SERVICE_NAME = _resolve_service_name()


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        headers[k.strip()] = unquote(v.strip())
    return headers


def init_tracer_provider() -> TracerProvider | None:
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        logger.info("otel_exporter_not_configured")
        return None

    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: SERVICE_NAME,
        ResourceAttributes.SERVICE_VERSION: SERVICE_VERSION,
        ResourceAttributes.SERVICE_NAMESPACE: settings.OTEL_SERVICE_NAMESPACE or "obsidian",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.APP_ENV,
        **({ResourceAttributes.SERVICE_INSTANCE_ID: settings.OTEL_SERVICE_INSTANCE_ID} if settings.OTEL_SERVICE_INSTANCE_ID else {}),
    })

    sampler = (
        ALWAYS_ON
        if settings.APP_ENV in ("development", "dev", "testing", "test")
        else ParentBased(TraceIdRatioBased(settings.OTEL_TRACE_SAMPLE_RATIO))
    )
    provider = TracerProvider(resource=resource, sampler=sampler)

    exporter = OTLPSpanExporter(
        endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/')}/v1/traces",
        headers=_parse_otlp_headers(settings.OTEL_EXPORTER_OTLP_HEADERS),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info("otel_tracer_initialized", service=SERVICE_NAME, endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    return provider
