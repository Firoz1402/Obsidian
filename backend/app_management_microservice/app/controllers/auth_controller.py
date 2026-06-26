from app.core.responses import success_response
from app.schemas.auth import FirebaseAuthRequest, RefreshTokenRequest
from app.services.auth_service import AuthService
from app.utils.logging import get_logger
from app.utils.tracing import set_login_attrs, set_login_email, hash_user_id

logger = get_logger(__name__)


class AuthController:
    @staticmethod
    async def firebase_auth(body: FirebaseAuthRequest) -> dict:
        set_login_attrs(device=body.device)
        claims = AuthService.verify_firebase_token(body.id_token)
        set_login_email(claims.get("email"))
        user, is_new = AuthService.resolve_user(claims)
        tokens = AuthService.create_session_tokens(user["id"])
        await AuthService.store_refresh_token(
            user["id"], tokens["refresh_token"], tokens["jti"]
        )

        action = "signup" if is_new else "login"
        set_login_attrs(user_id=user["id"])
        logger.info(
            f"auth_{action}",
            user_id=hash_user_id(user["id"]),
            device=body.device,
            provider="firebase",
        )

        return success_response(
            data={
                "user": _format_user(user, is_new),
                "tokens": _format_tokens(tokens),
            },
            message="Account created successfully." if is_new else "Logged in successfully.",
        )

    @staticmethod
    async def refresh(body: RefreshTokenRequest) -> dict:
        result = await AuthService.rotate_refresh_token(body.refresh_token)
        return success_response(
            data={"tokens": _format_tokens(result["tokens"])},
            message="Tokens refreshed successfully.",
        )

    @staticmethod
    async def logout(jti: str, refresh_token: str, exp: int) -> dict:
        await AuthService.logout(jti, refresh_token, exp)
        return success_response(message="Logged out successfully.")


def _format_user(user: dict, is_new: bool) -> dict:
    display = None
    if user.get("first_name"):
        display = user["first_name"]
        if user.get("last_name"):
            display += f" {user['last_name']}"

    return {
        "id": user["id"],
        "email": user.get("email"),
        "first_name": user.get("first_name"),
        "middle_name": user.get("middle_name"),
        "last_name": user.get("last_name"),
        "mobile": user.get("mobile"),
        "gender": user.get("gender"),
        "dob": user.get("dob"),
        "display_name": display,
        "profile_pic_path": user.get("profile_pic_path"),
        "is_new_user": is_new,
        "created_at": user.get("created_at"),
    }


def _format_tokens(tokens: dict) -> dict:
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens["token_type"],
        "expires_in": tokens["expires_in"],
    }
