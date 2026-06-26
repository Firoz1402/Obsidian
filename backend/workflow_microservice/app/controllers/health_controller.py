from app.config.observability import SERVICE_NAME
from app.services.health_service import HealthService


class HealthController:
    @staticmethod
    async def liveness() -> dict:
        return {"status": "ok", "service": SERVICE_NAME}

    @staticmethod
    async def readiness() -> dict:
        result = await HealthService.check_readiness()
        return {"service": SERVICE_NAME, **result}
