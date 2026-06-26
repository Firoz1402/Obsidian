from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Device = Literal["web", "android", "ios"]


class FirebaseAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_token: str = Field(..., description="Firebase ID token from client SDK")
    device: Device = Field(..., description="Client platform: web, android, or ios.")


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class AuthUser(BaseModel):
    id: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    profile_pic_path: Optional[str] = None
    is_new_user: bool = False
    created_at: datetime


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(BaseModel):
    user: AuthUser
    tokens: AuthTokens
