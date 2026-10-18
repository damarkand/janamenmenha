from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.container import Container
from app.core.errors import AuthError, ForbiddenError
from app.models.domain import Role, User

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                     c: Container = Depends(get_container)) -> User:
    if not creds:
        raise AuthError("Требуется авторизация")
    return c.auth.resolve_token(creds.credentials)


def require_roles(*roles: Role):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("Недостаточно прав для этого действия")
        return user
    return _dep
