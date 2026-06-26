from temporalio.client import Client, TLSConfig
from temporalio.contrib.opentelemetry import TracingInterceptor

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def connect_temporal() -> Client:
    tls: TLSConfig | bool = False
    if settings.TEMPORAL_TLS_CERT_PATH and settings.TEMPORAL_TLS_KEY_PATH:
        with open(settings.TEMPORAL_TLS_CERT_PATH, "rb") as f:
            cert = f.read()
        with open(settings.TEMPORAL_TLS_KEY_PATH, "rb") as f:
            key = f.read()
        tls = TLSConfig(client_cert=cert, client_private_key=key)

    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
        tls=tls,
        interceptors=[TracingInterceptor()],
    )
    logger.info(
        "temporal_connected",
        host=settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    return client
