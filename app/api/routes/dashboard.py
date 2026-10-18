from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_user, require_roles
from app.api.presenters import task_out
from app.container import Container
from app.models.domain import Role, User

router = APIRouter(prefix="/dashboard", tags=["Главная и графики"])


@router.get("/me", summary="Сводка сотрудника: карточки и данные для графиков")
def my_dashboard(user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    data = c.dashboard.me(user)
    data["upcoming_tasks"] = [task_out(c, t).model_dump(mode="json") for t in data["upcoming_tasks"]]
    return data


@router.get("/team", summary="Сводка по команде (руководитель — свои, HR — все)")
def team_dashboard(user: User = Depends(require_roles(Role.MANAGER, Role.HR)), c: Container = Depends(get_container)):
    return c.dashboard.team(user)
