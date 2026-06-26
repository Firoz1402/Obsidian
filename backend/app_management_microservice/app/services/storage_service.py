from app.config.filebase import filebase_proxy
from app.config.settings import settings
from app.core.exceptions import ExternalServiceError, ValidationError

PROFILE_PIC_PREFIX = "user_profile_pic"
PROFILE_PIC_FILENAME = "profile.jpg"


def profile_pic_object_path(user_id: str) -> str:
    return f"{PROFILE_PIC_PREFIX}/{user_id}/{PROFILE_PIC_FILENAME}"


class StorageService:
    @staticmethod
    def issue_profile_pic_upload_url(user_id: str, content_type: str) -> dict:
        allowed_types = {ct.strip() for ct in settings.AVATAR_ALLOWED_CONTENT_TYPES.split(",")}
        if content_type not in allowed_types:
            raise ValidationError(
                f"Unsupported content type. Allowed: {', '.join(sorted(allowed_types))}"
            )

        object_path = profile_pic_object_path(user_id)
        upload_url = _client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.FILEBASE_BUCKET,
                "Key": object_path,
                "ContentType": content_type,
            },
            ExpiresIn=settings.AVATAR_UPLOAD_URL_TTL_MINUTES * 60,
        )

        return {
            "upload_url": upload_url,
            "method": "PUT",
            "profile_pic_path": object_path,
            "bucket": settings.FILEBASE_BUCKET,
            "object_path": object_path,
            "content_type": content_type,
            "max_size_bytes": settings.AVATAR_MAX_SIZE_MB * 1024 * 1024,
        }

    @staticmethod
    def issue_profile_pic_download_url(profile_pic_path: str) -> dict:
        _validate_profile_pic_path(profile_pic_path)
        download_url = _client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.FILEBASE_BUCKET,
                "Key": profile_pic_path,
            },
            ExpiresIn=settings.AVATAR_UPLOAD_URL_TTL_MINUTES * 60,
        )
        return {
            "download_url": download_url,
            "profile_pic_path": profile_pic_path,
        }


def _client():
    if not filebase_proxy.client:
        raise ExternalServiceError("filebase", "Storage client not initialized.")
    return filebase_proxy.client


def _validate_profile_pic_path(path: str) -> None:
    parts = path.split("/")
    if len(parts) != 3 or parts[0] != PROFILE_PIC_PREFIX or parts[2] != PROFILE_PIC_FILENAME:
        raise ValidationError("Invalid profile picture path.")
