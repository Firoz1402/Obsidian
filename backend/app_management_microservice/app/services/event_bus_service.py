import json
from typing import AsyncIterator, Optional

from app.config.redis import redis_proxy
from app.config.settings import settings
from app.core.exceptions import ExternalServiceError
from app.utils.logging import get_logger
from app.utils.tracing import traced_call

logger = get_logger(__name__)


def _record_dep(duration_ms: float, attrs: dict) -> None:
    from app.config.observability import observability_proxy
    observability_proxy.record_dependency(duration_ms, attrs)


JOB_STREAM_PREFIX = "job:"
JOB_STREAM_SUFFIX = ":events"

TERMINAL_EVENT_TYPES = frozenset({"job.done", "job.failed"})


def stream_key(job_id: str) -> str:
    return f"{JOB_STREAM_PREFIX}{job_id}{JOB_STREAM_SUFFIX}"


class EventBusService:
    """Redis Streams-backed event bus for job progress events.

    Workers XADD events; the SSE endpoint XREADs with BLOCK + Last-Event-ID
    so disconnected clients can resume from where they left off.
    """

    @staticmethod
    async def publish(job_id: str, event_type: str, payload: Optional[dict] = None) -> str:
        client = redis_proxy.client
        if not client:
            raise ExternalServiceError("redis", "Event bus unavailable.")

        body = json.dumps({"type": event_type, "payload": payload or {}})
        key = stream_key(job_id)

        async with traced_call("redis", "redis.stream", "xadd", record_metric=_record_dep):
            msg_id = await client.xadd(key, {"data": body})

        if event_type in TERMINAL_EVENT_TYPES:
            async with traced_call("redis", "redis.stream", "expire", record_metric=_record_dep):
                await client.expire(key, settings.INVESTIGATION_EVENT_STREAM_TTL_SECONDS)

        return msg_id

    @staticmethod
    async def subscribe(
        job_id: str,
        last_id: str = "0",
        block_ms: int = 30000,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Yields (msg_id, event_dict) until a terminal event or client disconnect.

        last_id semantics:
          - "0"  → replay from the beginning of the stream
          - "$"  → only events emitted after subscription
          - "<id>" → resume after this id (used with SSE Last-Event-ID header)
        """
        client = redis_proxy.client
        if not client:
            raise ExternalServiceError("redis", "Event bus unavailable.")

        key = stream_key(job_id)
        cursor = last_id

        while True:
            async with traced_call("redis", "redis.stream", "xread", record_metric=_record_dep):
                result = await client.xread({key: cursor}, block=block_ms, count=50)

            if not result:
                yield ("", {"type": "ping", "payload": {}})
                continue

            for _stream, messages in result:
                for msg_id, fields in messages:
                    cursor = msg_id
                    raw = fields.get("data") if isinstance(fields, dict) else None
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("event_bus_bad_payload", msg_id=msg_id, job_id=job_id)
                        continue
                    yield (msg_id, event)
                    if event.get("type") in TERMINAL_EVENT_TYPES:
                        return
