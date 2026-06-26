import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from firebase_admin import auth as firebase_auth

from app.config.firebase import firebase_proxy
from app.config.observability import observability_proxy
from app.config.redis import redis_proxy
from app.config.settings import settings
from app.config.supabase import supabase_proxy
from app.core.exceptions import AuthenticationError, ExternalServiceError
from app.utils.logging import get_logger
from app.utils.tracing import hash_user_id, traced_call_sync

logger = get_logger(__name__)


def _record_dep(duration_ms: float, attrs: dict) -> None:
    observability_proxy.record_dependency(duration_ms, attrs)


def _exec_db(db, table, op, builder):
    with traced_call_sync("db", f"supabase.{table}", op, record_metric=_record_dep):
        return builder.execute()


REFRESH_TOKEN_BYTES = 64
REDIS_BLOCKLIST_PREFIX = "token:blocklist:"
REDIS_REFRESH_PREFIX = "token:refresh:"
REDIS_USER_PROFILE_PREFIX = "token:user_profile:"
USER_PROFILE_CACHE_TTL = 600

GOOGLE_PROVIDER = "google"


class AuthService:
    @staticmethod
    def verify_firebase_token(id_token: str) -> dict:
        try:
            return firebase_proxy.verify_id_token(id_token)
        except firebase_auth.ExpiredIdTokenError:
            raise AuthenticationError("Firebase token has expired.")
        except firebase_auth.RevokedIdTokenError:
            raise AuthenticationError("Firebase token has been revoked.")
        except firebase_auth.InvalidIdTokenError:
            raise AuthenticationError("Invalid Firebase token.")
        except Exception as e:
            logger.error("firebase_verify_failed", extra={"error": str(e)})
            raise ExternalServiceError("firebase", "Token verification failed.")

    @staticmethod
    def resolve_user(firebase_claims: dict) -> tuple[dict, bool]:
        db = supabase_proxy.client
        if not db:
            raise ExternalServiceError("supabase", "Database client not initialized.")

        firebase_uid = firebase_claims["uid"]
        email = firebase_claims.get("email")

        identity_resp = (
            _exec_db(db, "auth_identities", "select", db.table("auth_identities")
            .select("user_id")
            .eq("provider", GOOGLE_PROVIDER)
            .eq("provider_user_id", firebase_uid)
            .maybe_single()
            )
        )
        if identity_resp and identity_resp.data:
            user = _get_user_by_id(db, identity_resp.data["user_id"])
            if user:
                _update_last_login(db, user["id"])
                return user, False

        first_name, last_name = _split_name(firebase_claims.get("name", ""))
        new_user_id = str(uuid.uuid4())
        user_resp = _exec_db(db, "users", "insert", db.table("users").insert({
            "id": new_user_id,
            "legacy_id": new_user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "is_email_verified": firebase_claims.get("email_verified", False),
            "last_login_at": datetime.now(timezone.utc).isoformat(),
        }))
        user = user_resp.data[0]

        _create_auth_identity(
            db,
            user_id=new_user_id,
            provider=GOOGLE_PROVIDER,
            provider_user_id=firebase_uid,
            email=email,
            is_primary=True,
        )

        logger.info(
            "user_created",
            extra={"hashed_user_uuid": hash_user_id(new_user_id), "provider": GOOGLE_PROVIDER},
        )
        return user, True

    @staticmethod
    def create_session_tokens(user_id: str) -> dict:
        now = datetime.now(timezone.utc)
        access_exp = now + timedelta(hours=settings.ACCESS_TOKEN_EXPIRY_HOURS)
        jti = uuid.uuid4().hex

        access_token = jwt.encode(
            {
                "sub": user_id,
                "iat": now,
                "exp": access_exp,
                "jti": jti,
                "type": "access",
            },
            settings.APP_SECRET_KEY,
            algorithm="HS256",
        )

        return {
            "access_token": access_token,
            "refresh_token": secrets.token_urlsafe(REFRESH_TOKEN_BYTES),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRY_HOURS * 3600,
            "jti": jti,
        }

    @staticmethod
    async def store_refresh_token(user_id: str, refresh_token: str, jti: str) -> None:
        if not redis_proxy.client:
            return
        ttl = settings.REFRESH_TOKEN_EXPIRY_HOURS * 3600
        await redis_proxy.client.setex(
            f"{REDIS_REFRESH_PREFIX}{refresh_token}", ttl, f"{user_id}:{jti}"
        )

    @staticmethod
    async def rotate_refresh_token(refresh_token: str) -> dict:
        if not redis_proxy.client:
            raise AuthenticationError("Session service unavailable.")

        key = f"{REDIS_REFRESH_PREFIX}{refresh_token}"
        stored = await redis_proxy.client.get(key)
        if not stored:
            raise AuthenticationError("Invalid or expired refresh token.")

        stored_str = stored if isinstance(stored, str) else stored.decode()
        user_id, old_jti = stored_str.split(":", 1)

        await redis_proxy.client.delete(key)
        await AuthService.blocklist_token(
            old_jti, ttl=settings.ACCESS_TOKEN_EXPIRY_HOURS * 3600
        )

        tokens = AuthService.create_session_tokens(user_id)
        await AuthService.store_refresh_token(user_id, tokens["refresh_token"], tokens["jti"])
        return {"user_id": user_id, "tokens": tokens}

    @staticmethod
    def verify_access_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Access token has expired.")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid access token.")

        if payload.get("type") != "access":
            raise AuthenticationError("Invalid token type.")
        return payload

    @staticmethod
    async def is_token_blocklisted(jti: str) -> bool:
        if not redis_proxy.client:
            return False
        return bool(await redis_proxy.client.exists(f"{REDIS_BLOCKLIST_PREFIX}{jti}"))

    @staticmethod
    async def get_user_by_id(user_id: str) -> dict:
        cache_key = f"{REDIS_USER_PROFILE_PREFIX}{user_id}"

        if redis_proxy.client:
            cached = await redis_proxy.client.get(cache_key)
            if cached:
                return json.loads(cached if isinstance(cached, str) else cached.decode())

        db = supabase_proxy.client
        if not db:
            raise ExternalServiceError("supabase", "Database client not initialized.")

        user_resp = (
            _exec_db(db, "users", "select", db.table("users")
            .select("*")
            .eq("id", user_id)
            .eq("deleted_account", False)
            .maybe_single()
            )
        )
        if not user_resp or not user_resp.data:
            raise AuthenticationError("User not found.")

        if redis_proxy.client:
            await redis_proxy.client.setex(
                cache_key, USER_PROFILE_CACHE_TTL, json.dumps(user_resp.data)
            )
        return user_resp.data

    @staticmethod
    async def logout(jti: str, refresh_token: str, exp: int) -> None:
        now = int(datetime.now(timezone.utc).timestamp())
        remaining_ttl = max(exp - now, 1)
        await AuthService.blocklist_token(jti, ttl=remaining_ttl)
        if redis_proxy.client:
            await redis_proxy.client.delete(f"{REDIS_REFRESH_PREFIX}{refresh_token}")

    @staticmethod
    async def blocklist_token(jti: str, ttl: int) -> None:
        if not redis_proxy.client:
            return
        await redis_proxy.client.setex(f"{REDIS_BLOCKLIST_PREFIX}{jti}", ttl, "1")

    @staticmethod
    async def delete_account(user_id: str, jti: str) -> None:
        db = supabase_proxy.client
        if not db:
            raise ExternalServiceError("supabase", "Database client not initialized.")

        identity_resp = (
            _exec_db(db, "auth_identities", "select", db.table("auth_identities")
            .select("provider_user_id")
            .eq("user_id", user_id)
            .limit(1)
            )
        )
        fb_uid = (
            identity_resp.data[0]["provider_user_id"]
            if identity_resp and identity_resp.data
            else None
        )

        _exec_db(db, "users", "update", db.table("users").update({
            "deleted_account": True,
            "email": None,
            "legacy_id": None,
            "first_name": None,
            "last_name": None,
            "middle_name": None,
            "mobile": None,
            "dob": None,
            "profile_pic_path": None,
        }).eq("id", user_id))

        _exec_db(db, "auth_identities", "delete", db.table("auth_identities").delete().eq("user_id", user_id))

        await AuthService.blocklist_token(jti, ttl=settings.ACCESS_TOKEN_EXPIRY_HOURS * 3600)

        if redis_proxy.client:
            async for key in redis_proxy.client.scan_iter(
                match=f"{REDIS_REFRESH_PREFIX}*", count=100
            ):
                stored = await redis_proxy.client.get(key)
                if not stored:
                    continue
                stored_str = stored if isinstance(stored, str) else stored.decode()
                if stored_str.startswith(f"{user_id}:"):
                    await redis_proxy.client.delete(key)

        if fb_uid:
            try:
                firebase_auth.delete_user(fb_uid, app=firebase_proxy.app)
            except Exception as e:
                logger.warning(
                    "firebase_delete_failed",
                    extra={"hashed_user_uuid": hash_user_id(user_id), "error": str(e)},
                )

        logger.info("account_deleted", extra={"hashed_user_uuid": hash_user_id(user_id)})


def _get_user_by_id(db, user_id: str) -> Optional[dict]:
    with traced_call_sync("db", "supabase.users", "select_by_id", record_metric=_record_dep):
        resp = (
            _exec_db(db, "users", "select", db.table("users")
            .select("*")
            .eq("id", user_id)
            .eq("deleted_account", False)
            .maybe_single()
            )
        )
    return resp.data if resp else None


def _update_last_login(db, user_id: str) -> None:
    with traced_call_sync("db", "supabase.users", "update_last_login", record_metric=_record_dep):
        _exec_db(db, "users", "update", db.table("users").update({
            "last_login_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id))


def _create_auth_identity(
    db,
    user_id: str,
    provider: str,
    provider_user_id: str,
    email: Optional[str],
    is_primary: bool,
) -> None:
    _exec_db(db, "auth_identities", "insert", db.table("auth_identities").insert({
        "user_id": user_id,
        "provider": provider,
        "provider_user_id": provider_user_id,
        "email": email,
        "is_primary": is_primary,
    }))


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(None, 1)
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")
