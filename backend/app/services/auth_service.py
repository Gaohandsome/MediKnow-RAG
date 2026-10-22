"""用户注册/登录服务。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.captcha import captcha_store
from app.core.config import settings
from app.core.exceptions import BizError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut


def _check_captcha(captcha_id: str, captcha_code: str) -> None:
    if not captcha_store.verify(captcha_id, captcha_code):
        raise BizError("验证码错误或已过期，请重新获取", status_code=400)


def register(db: Session, payload: RegisterRequest) -> UserOut:
    """注册新用户。"""
    _check_captcha(payload.captcha_id, payload.captcha_code)

    if payload.password != payload.confirm_password:
        raise BizError("两次输入的密码不一致", status_code=400)

    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists:
        raise BizError("该账号已存在，请更换账号名称", status_code=409)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=payload.username,
    )
    db.add(user)
    db.flush()
    return UserOut.model_validate(user)


def login(db: Session, payload: LoginRequest) -> TokenOut:
    """账号密码 + 验证码登录。"""
    _check_captcha(payload.captcha_id, payload.captcha_code)

    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise BizError("账号或密码错误", status_code=401)

    token = create_access_token(user.id, extra={"username": user.username})
    return TokenOut(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise BizError("用户不存在", status_code=404)
    return user
