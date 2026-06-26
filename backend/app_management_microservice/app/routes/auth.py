from fastapi import APIRouter, Depends

from app.controllers.auth_controller import AuthController
from app.core.dependencies import get_current_user
from app.schemas.auth import FirebaseAuthRequest, RefreshTokenRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/google")
async def firebase_auth(body: FirebaseAuthRequest):
    return await AuthController.firebase_auth(body)


@router.post("/refresh")
async def refresh_token(body: RefreshTokenRequest):
    return await AuthController.refresh(body)


@router.post("/logout")
async def logout(
    body: RefreshTokenRequest,
    current_user: dict = Depends(get_current_user),
):
    return await AuthController.logout(
        jti=current_user["jti"],
        refresh_token=body.refresh_token,
        exp=current_user["exp"],
    )
