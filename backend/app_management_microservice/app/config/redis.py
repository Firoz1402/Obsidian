import structlog
from typing import Optional

import redis.asyncio as redis

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RedisClientProxy:
    client: Optional[redis.Redis] = None

    async def init_client(self) -> None:
        if settings.REDIS_URL:
            kwargs = {"decode_responses": True}
            if settings.REDIS_PASSWORD:
                kwargs["password"] = settings.REDIS_PASSWORD
            self.client = redis.from_url(settings.REDIS_URL, **kwargs)
        elif settings.REDIS_HOST:
            kwargs = {
                "host": settings.REDIS_HOST,
                "port": settings.REDIS_PORT,
                "decode_responses": True,
            }
            if settings.REDIS_USERNAME:
                kwargs["username"] = settings.REDIS_USERNAME
            if settings.REDIS_PASSWORD:
                kwargs["password"] = settings.REDIS_PASSWORD
            self.client = redis.Redis(**kwargs)
        else:
            logger.warning("redis_configuration_missing")

    async def close_client(self) -> None:
        if self.client:
            await self.client.aclose()


redis_proxy = RedisClientProxy()
