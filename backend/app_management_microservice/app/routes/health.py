from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.controllers.health_controller import HealthController

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return await HealthController.check_health()


@router.get("/health/ready")
async def readiness_check():
    return await HealthController.check_readiness()


@router.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
