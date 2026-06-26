from typing import Any, Dict

from fastapi.responses import JSONResponse

from app.core.responses import success_response
from app.services.health_service import HealthService


class HealthController:
    @staticmethod
    async def check_health() -> Dict[str, Any]:
        return success_response(data=HealthService.check_liveness())

    @staticmethod
    async def check_readiness() -> JSONResponse:
        health_data = await HealthService.check_readiness()
        status_code = 200 if health_data.get("status") == "ready" else 503
        return JSONResponse(
            status_code=status_code, 
            content=success_response(data=health_data)
        )
