# Health probes intentionally bypass the `traced_call` wrapper that the
# rest of the codebase uses for external I/O. They run on a 30s background
# loop (and on /health/ready hits) and would otherwise dominate the
# dependency-call metrics with noise that has nothing to do with real
# request traffic. They DO emit `app_dependency_up` gauges separately,
# which is what powers the status tiles on the Grafana dashboard.
import asyncio
from typing import Any, Dict

from app.config.redis import redis_proxy
from app.config.settings import settings
from app.config.supabase import supabase_proxy


class HealthService:
    @staticmethod
    def check_liveness() -> Dict[str, str]:
        return {"status": "healthy", "version": "1.0.0"}

    @staticmethod
    async def check_readiness() -> Dict[str, Any]:
        statuses: Dict[str, str] = {
            "supabase": "not_checked",
            "cache_redis": "not_checked",
            "redis_queue": "not_checked",
            "temporal": "not_checked",
            "temporal_db": "not_checked",
        }

        async def check_cache_redis() -> None:
            if not redis_proxy.client:
                statuses["cache_redis"] = "skipped"
                return
            try:
                await redis_proxy.client.ping()
                statuses["cache_redis"] = "healthy"
            except Exception as e:
                statuses["cache_redis"] = f"unhealthy: {e}"

        async def check_redis_queue() -> None:
            # Until a dedicated queue Redis is wired up, share the cache client
            # so the queue tile reflects connectivity to the Redis instance
            # currently servicing both roles.
            if not redis_proxy.client:
                statuses["redis_queue"] = "skipped"
                return
            try:
                await redis_proxy.client.ping()
                statuses["redis_queue"] = "healthy"
            except Exception as e:
                statuses["redis_queue"] = f"unhealthy: {e}"

        async def check_supabase() -> None:
            if not supabase_proxy.client:
                statuses["supabase"] = "skipped"
                return
            try:
                await asyncio.to_thread(
                    supabase_proxy.client.table("users").select("id").limit(1).execute
                )
                statuses["supabase"] = "healthy"
            except Exception as e:
                statuses["supabase"] = f"unhealthy: {e}"

        async def check_temporal() -> None:
            host = getattr(settings, "TEMPORAL_HOST", "")
            if not host:
                statuses["temporal"] = "skipped"
                return
            try:
                from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
                from temporalio.client import Client
            except ImportError:
                statuses["temporal"] = "skipped"
                return
            try:
                client = await asyncio.wait_for(Client.connect(host), timeout=2.0)
                await asyncio.wait_for(
                    client.workflow_service.get_system_info(GetSystemInfoRequest()),
                    timeout=2.0,
                )
                statuses["temporal"] = "healthy"
            except Exception as e:
                statuses["temporal"] = f"unhealthy: {e}"

        async def check_temporal_db() -> None:
            dsn = (
                getattr(settings, "TEMPORAL_DB_URL", "")
                or getattr(settings, "TEMPORAL_POSTGRES_URL", "")
            )
            if not dsn:
                statuses["temporal_db"] = "skipped"
                return
            try:
                import asyncpg
                conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=2.0)
                try:
                    await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=1.0)
                    statuses["temporal_db"] = "healthy"
                finally:
                    await conn.close()
            except ImportError:
                statuses["temporal_db"] = "skipped"
            except Exception as e:
                statuses["temporal_db"] = f"unhealthy: {e}"

        await asyncio.gather(
            check_cache_redis(),
            check_redis_queue(),
            check_supabase(),
            check_temporal(),
            check_temporal_db(),
        )

        overall = "ready"
        if any(v.startswith("unhealthy") for v in statuses.values()):
            overall = "degraded"

        from app.config.observability import observability_proxy
        if hasattr(observability_proxy, "dependency_up") and observability_proxy.dependency_up is not None:
            for dep_name, status_str in statuses.items():
                if status_str == "skipped" or status_str == "not_checked":
                    continue
                is_up = 1 if status_str == "healthy" else 0
                try:
                    observability_proxy.dependency_up.set(is_up, {"dependency": dep_name})
                except Exception:
                    pass

        return {"status": overall, "checks": statuses}
