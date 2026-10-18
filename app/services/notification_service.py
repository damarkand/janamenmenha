from __future__ import annotations

from app.core.errors import NotFoundError
from app.models.domain import Notification, NotificationType, User
from app.repositories.memory import NotificationRepository


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self._repo = repo

    def notify(self, user_id: str, type_: NotificationType, title: str, message: str,
               link: str | None = None) -> Notification:
        return self._repo.add(Notification(id=self._repo.next_id(), user_id=user_id, type=type_,
                                           title=title, message=message, link=link))

    def list_for(self, actor: User, unread_only: bool = False) -> list[Notification]:
        items = self._repo.by_user(actor.id)
        return [n for n in items if not n.read] if unread_only else items

    def unread_count(self, user_id: str) -> int:
        return sum(1 for n in self._repo.by_user(user_id) if not n.read)

    def mark_read(self, actor: User, notification_id: str) -> Notification:
        n = self._repo.get(notification_id)
        if not n or n.user_id != actor.id:
            raise NotFoundError("Уведомление не найдено")
        n.read = True
        return self._repo.save(n)

    def mark_all_read(self, actor: User) -> int:
        changed = 0
        for n in self._repo.by_user(actor.id):
            if not n.read:
                n.read = True
                self._repo.save(n)
                changed += 1
        return changed
