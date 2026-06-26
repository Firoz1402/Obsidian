from app.utils.logging import get_logger

from app.core.responses import success_response
from app.schemas.user import (
    ProfilePicDownloadUrlRequest,
    ProfilePicUploadUrlRequest,
    UpdateProfileRequest,
)
from app.services.auth_service import AuthService
from app.services.storage_service import StorageService
from app.services.user_service import UserService

logger = get_logger(__name__)


class UserController:
    @staticmethod
    async def get_me(user_id: str) -> dict:
        user = await AuthService.get_user_by_id(user_id)
        return success_response(
            data={"user": _format_user(user)},
            message="User profile retrieved.",
        )

    @staticmethod
    async def update_profile(user_id: str, body: UpdateProfileRequest) -> dict:
        updates = body.model_dump(exclude_none=True)
        user = await UserService.update_profile(user_id, updates)
        return success_response(
            data={"user": _format_user(user)},
            message="Profile updated successfully.",
        )

    @staticmethod
    async def get_profile_pic_upload_url(user_id: str, body: ProfilePicUploadUrlRequest) -> dict:
        result = StorageService.issue_profile_pic_upload_url(
            user_id=user_id,
            content_type=body.content_type,
        )
        return success_response(
            data=result,
            message="Profile picture upload URL issued.",
        )

    @staticmethod
    async def confirm_profile_pic(user_id: str) -> dict:
        user = await UserService.set_profile_pic(user_id)
        return success_response(
            data={"user": _format_user(user)},
            message="Profile picture updated successfully.",
        )

    @staticmethod
    async def get_profile_pic_download_url(body: ProfilePicDownloadUrlRequest) -> dict:
        result = StorageService.issue_profile_pic_download_url(body.profile_pic_path)
        return success_response(
            data=result,
            message="Profile picture download URL issued.",
        )

    @staticmethod
    async def delete_account(user_id: str, jti: str) -> dict:
        await AuthService.delete_account(user_id, jti)
        return success_response(message="Account deleted successfully.")


def _format_user(user: dict) -> dict:
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
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }
