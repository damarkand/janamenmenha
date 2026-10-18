from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_user
from app.api.presenters import notification_out
from app.container import Container
from app.models.domain import User
from app.models.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Уведомления"])


@router.get("", response_model=list[NotificationOut], summary="Мои уведомления (новые сверху)")
def list_notifications(unread_only: bool = False, user: User = Depends(get_current_user),
                       c: Container = Depends(get_container)):
    return [notification_out(n) for n in c.notifications.list_for(user, unread_only)]


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Отметить прочитанным")
def mark_read(notification_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return notification_out(c.notifications.mark_read(user, notification_id))


@router.post("/read-all", summary="Отметить все прочитанными")
def mark_all(user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return {"updated": c.notifications.mark_all_read(user)}
