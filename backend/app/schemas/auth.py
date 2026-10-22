"""认证相关数据结构。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="账号名称")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    confirm_password: str = Field(..., min_length=6, max_length=64, description="确认密码")
    captcha_id: str = Field(..., description="验证码标识")
    captcha_code: str = Field(..., min_length=1, max_length=8, description="验证码")

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        value = value.strip()
        if not value.isalnum():
            raise ValueError("账号只能包含字母和数字")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("密码不能包含首尾空格")
        return value


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32, description="账号名称")
    password: str = Field(..., min_length=1, max_length=64, description="密码")
    captcha_id: str = Field(..., description="验证码标识")
    captcha_code: str = Field(..., min_length=1, max_length=8, description="验证码")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
