from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_user
from app.container import Container
from app.models.domain import User
from app.models.schemas import LoginIn, ProfileOut, TokenOut

router = APIRouter(prefix="/auth", tags=["Авторизация"])


@router.post("/login", response_model=TokenOut, summary="Вход по email/паролю, возвращает JWT")
def login(body: LoginIn, c: Container = Depends(get_container)):
    user, token, ttl = c.auth.login(body.email, body.password)
    return TokenOut(access_token=token, expires_in=ttl, role=user.role, user_id=user.id)


@router.get("/me", response_model=ProfileOut, summary="Текущий пользователь")
def me(user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return c.profiles.get_profile(user, user.id)
