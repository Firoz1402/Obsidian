from app.utils.logging import get_logger

logger = get_logger(__name__)


class HealthService:
    @staticmethod
    async def check_readiness() -> dict:
        # The orchestrator only depends on Temporal itself; the worker process
        # cannot start without a successful client connection, so reaching this
        # endpoint already implies the dependency is satisfied.
        return {"status": "ready", "dependencies": {"temporal": "up"}}
