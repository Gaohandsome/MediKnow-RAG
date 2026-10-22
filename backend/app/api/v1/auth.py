"""认证接口：验证码、注册、登录、当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.captcha import new_captcha
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.schemas.common import ok
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/captcha", summary="获取图形验证码")
def get_captcha() -> dict:
    captcha_id, image = new_captcha()
    return ok({"captcha_id": captcha_id, "image": image})


@router.post("/register", summary="用户注册")
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    user = auth_service.register(db, payload)
    return ok(user.model_dump(mode="json"), message="注册成功")


@router.post("/login", summary="用户登录", response_model=None)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    token: TokenOut = auth_service.login(db, payload)
    return ok(token.model_dump(mode="json"), message="登录成功")


@router.get("/me", summary="获取当前登录用户")
def me(current_user: User = Depends(get_current_user)) -> dict:
    return ok(UserOut.model_validate(current_user).model_dump(mode="json"))
