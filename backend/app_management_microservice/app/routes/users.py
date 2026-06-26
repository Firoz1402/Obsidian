from fastapi import APIRouter, Depends

from app.controllers.user_controller import UserController
from app.core.dependencies import get_current_user
from app.schemas.user import (
    ProfilePicDownloadUrlRequest,
    ProfilePicUploadUrlRequest,
    UpdateProfileRequest,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return await UserController.get_me(user_id=current_user["sub"])


@router.patch("/me")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    return await UserController.update_profile(
        user_id=current_user["sub"], body=body
    )


@router.delete("/me")
async def delete_account(current_user: dict = Depends(get_current_user)):
    return await UserController.delete_account(
        user_id=current_user["sub"],
        jti=current_user["jti"],
    )


@router.post("/me/profile-pic/upload-url")
async def get_profile_pic_upload_url(
    body: ProfilePicUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
):
    return await UserController.get_profile_pic_upload_url(
        user_id=current_user["sub"], body=body
    )


@router.put("/me/profile-pic")
async def confirm_profile_pic(current_user: dict = Depends(get_current_user)):
    return await UserController.confirm_profile_pic(user_id=current_user["sub"])


@router.post("/profile-pic/download-url")
async def get_profile_pic_download_url(
    body: ProfilePicDownloadUrlRequest,
    current_user: dict = Depends(get_current_user),
):
    return await UserController.get_profile_pic_download_url(body)
