import structlog
from temporalio.client import Client

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TemporalClientProxy:
    client: Client | None = None

    async def init_client(self) -> None:
        if settings.TEMPORAL_HOST:
            try:
                self.client = await Client.connect(
                    settings.TEMPORAL_HOST,
                    namespace=settings.TEMPORAL_NAMESPACE,
                )
                logger.info("temporal_client_initialized", host=settings.TEMPORAL_HOST)
            except Exception as e:
                logger.error("temporal_client_init_failed", error=str(e))
        else:
            logger.warning("temporal_configuration_missing")


temporal_proxy = TemporalClientProxy()
