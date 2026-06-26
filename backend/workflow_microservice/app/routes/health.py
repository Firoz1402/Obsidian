from fastapi import APIRouter

from app.controllers.health_controller import HealthController

router = APIRouter(tags=["Health"])


@router.get("/health")
async def liveness() -> dict:
    return await HealthController.liveness()


@router.get("/health/ready")
async def readiness() -> dict:
    return await HealthController.readiness()
