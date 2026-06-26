from datetime import datetime, timezone
from typing import Any, Dict

from app.config.observability import observability_proxy
from app.config.redis import redis_proxy
from app.config.supabase import supabase_proxy
from app.core.exceptions import ExternalServiceError, NotFoundError, ValidationError
from app.services.storage_service import profile_pic_object_path
from app.utils.logging import get_logger
from app.utils.tracing import traced_call_sync

logger = get_logger(__name__)

USER_PROFILE_CACHE_PREFIX = "token:user_profile:"
UPDATABLE_FIELDS = {"first_name", "middle_name", "last_name", "gender", "dob"}


def _record_dep(duration_ms: float, attrs: dict) -> None:
    observability_proxy.record_dependency(duration_ms, attrs)


class UserService:
    @staticmethod
    async def update_profile(user_id: str, updates: Dict[str, Any]) -> dict:
        clean = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in updates.items()
            if k in UPDATABLE_FIELDS and v is not None
        }
        if not clean:
            raise ValidationError("No valid fields to update.")

        db = supabase_proxy.client
        if not db:
            raise ExternalServiceError("supabase", "Database client not initialized.")

        with traced_call_sync("db", "supabase.users", "select_profile", record_metric=_record_dep):
            current_resp = (
                db.table("users")
                .select(", ".join(UPDATABLE_FIELDS))
                .eq("id", user_id)
                .eq("deleted_account", False)
                .maybe_single()
                .execute()
            )
        if not current_resp or not current_resp.data:
            raise NotFoundError("User", user_id)

        current = current_resp.data
        changed = {
            k: v for k, v in clean.items() if _normalize(current.get(k)) != _normalize(v)
        }
        if not changed:
            raise ValidationError(
                "No changes detected. Submitted values match the current profile."
            )

        changed["updated_at"] = datetime.now(timezone.utc).isoformat()

        with traced_call_sync("db", "supabase.users", "update_profile", record_metric=_record_dep):
            resp = (
                db.table("users")
                .update(changed)
                .eq("id", user_id)
                .eq("deleted_account", False)
                .execute()
            )
        if not resp.data:
            raise NotFoundError("User", user_id)

        await UserService._invalidate_cache(user_id)
        return resp.data[0]

    @staticmethod
    async def set_profile_pic(user_id: str) -> dict:
        db = supabase_proxy.client
        if not db:
            raise ExternalServiceError("supabase", "Database client not initialized.")

        with traced_call_sync("db", "supabase.users", "update_profile_pic", record_metric=_record_dep):
            resp = (
                db.table("users")
                .update({
                    "profile_pic_path": profile_pic_object_path(user_id),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", user_id)
                .eq("deleted_account", False)
                .execute()
            )
        if not resp.data:
            raise NotFoundError("User", user_id)

        await UserService._invalidate_cache(user_id)
        return resp.data[0]

    @staticmethod
    async def _invalidate_cache(user_id: str) -> None:
        if redis_proxy.client:
            await redis_proxy.client.delete(f"{USER_PROFILE_CACHE_PREFIX}{user_id}")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
