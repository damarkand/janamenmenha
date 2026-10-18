from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_user, require_roles
from app.container import Container
from app.models.domain import Role, User
from app.models.schemas import ProfileOut, TeamMemberOut

router = APIRouter(prefix="/users", tags=["Профили (только чтение, 1С:ЗУП)"])


@router.get("/me", response_model=ProfileOut, summary="Мой профиль (только чтение)")
def my_profile(user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return c.profiles.get_profile(user, user.id)


@router.get("", response_model=list[TeamMemberOut],
            summary="Команда: руководитель — прямые подчинённые, HR — все сотрудники")
def list_users(user: User = Depends(require_roles(Role.MANAGER, Role.HR)), c: Container = Depends(get_container)):
    return c.profiles.list_visible_users(user)


@router.get("/{user_id}", response_model=ProfileOut, summary="Профиль сотрудника (в пределах прав)")
def get_profile(user_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return c.profiles.get_profile(user, user_id)
