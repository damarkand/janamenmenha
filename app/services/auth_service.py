from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AuthError
from app.core.security import create_access_token, decode_access_token, verify_password
from app.models.domain import User
from app.repositories.memory import UserRepository


class AuthService:
    def __init__(self, users: UserRepository, settings: Settings):
        self._users = users
        self._settings = settings

    def login(self, email: str, password: str) -> tuple[User, str, int]:
        user = self._users.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise AuthError("Неверный email или пароль")
        token, ttl = create_access_token(user.id, user.role.value, self._settings)
        return user, token, ttl

    def resolve_token(self, token: str) -> User:
        payload = decode_access_token(token, self._settings)
        user = self._users.get(payload.get("sub", ""))
        if not user:
            raise AuthError("Пользователь не найден")
        return user
