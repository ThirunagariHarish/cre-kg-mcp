from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
import bcrypt as _bcrypt
from jose import jwt
from pydantic import BaseModel

from ...core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str


@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> Token:
    settings = get_settings()

    if form.username != settings.dashboard_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not settings.dashboard_password_hash:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured — set DASHBOARD_PASSWORD_HASH via Doppler",
        )

    if not _verify_password(form.password, settings.dashboard_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode(
        {"sub": form.username, "exp": expire},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return Token(access_token=token, token_type="bearer", username=form.username)
