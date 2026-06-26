from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    middle_name: Optional[str] = Field(default=None, max_length=80)
    last_name: Optional[str] = Field(default=None, max_length=80)
    gender: Optional[Literal["male", "female", "other", "prefer_not_to_say"]] = None
    dob: Optional[date] = None


class ProfilePicUploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: str = Field(..., min_length=1, max_length=80)


class ProfilePicDownloadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_pic_path: str = Field(..., min_length=1, max_length=512)
