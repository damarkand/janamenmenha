from __future__ import annotations

from datetime import date
from itertools import count
from threading import RLock
from typing import Callable, Generic, Iterable, TypeVar

from pydantic import BaseModel

from app.models.domain import (
    Course, Enrollment, Escalation, HRRequest, Notification, RequestStatus, RequestType, Role, Task, TimeEntry,
    User, WorkSchedule,
)

T = TypeVar("T", bound=BaseModel)


class InMemoryRepository(Generic[T]):
    def __init__(self, prefix: str, items: Iterable[T] = ()):
        self._prefix = prefix
        self._items: dict[str, T] = {i.id: i for i in items}
        self._lock = RLock()
        self._seq = count(len(self._items) + 1)

    def next_id(self) -> str:
        with self._lock:
            while True:
                candidate = f"{self._prefix}-{next(self._seq)}"
                if candidate not in self._items:
                    return candidate

    def get(self, item_id: str) -> T | None:
        return self._items.get(item_id)

    def list(self, predicate: Callable[[T], bool] | None = None) -> list[T]:
        with self._lock:
            items = list(self._items.values())
        return [i for i in items if predicate is None or predicate(i)]

    def add(self, item: T) -> T:
        with self._lock:
            self._items[item.id] = item
        return item

    save = add

    def delete(self, item_id: str) -> None:
        with self._lock:
            self._items.pop(item_id, None)


class UserRepository(InMemoryRepository[User]):
    def get_by_email(self, email: str) -> User | None:
        email = email.strip().lower()
        return next((u for u in self.list() if u.email.lower() == email), None)

    def direct_reports(self, manager_id: str) -> list[User]:
        return self.list(lambda u: u.manager_id == manager_id)

    def by_role(self, role: Role) -> list[User]:
        return self.list(lambda u: u.role == role)


class RequestRepository(InMemoryRepository[HRRequest]):
    def for_users(self, user_ids: set[str]) -> list[HRRequest]:
        return self.list(lambda r: r.user_id in user_ids)

    def by_user(self, user_id: str, type_: RequestType | None = None,
                statuses: set[RequestStatus] | None = None) -> list[HRRequest]:
        return self.list(lambda r: r.user_id == user_id
                         and (type_ is None or r.type == type_)
                         and (statuses is None or r.status in statuses))


class CourseRepository(InMemoryRepository[Course]):
    pass


class EnrollmentRepository(InMemoryRepository[Enrollment]):
    def find(self, user_id: str, course_id: str) -> Enrollment | None:
        return next((e for e in self.list() if e.user_id == user_id and e.course_id == course_id), None)

    def by_user(self, user_id: str) -> list[Enrollment]:
        return self.list(lambda e: e.user_id == user_id)


class NotificationRepository(InMemoryRepository[Notification]):
    def by_user(self, user_id: str) -> list[Notification]:
        return sorted(self.list(lambda n: n.user_id == user_id), key=lambda n: n.created_at, reverse=True)


class EscalationRepository(InMemoryRepository[Escalation]):
    pass


class TaskRepository(InMemoryRepository[Task]):
    def for_users(self, user_ids: set[str]) -> list[Task]:
        return self.list(lambda t: t.user_id in user_ids)


class TimeEntryRepository(InMemoryRepository[TimeEntry]):
    def by_user(self, user_id: str, start: date, end: date) -> list[TimeEntry]:
        return sorted(self.list(lambda e: e.user_id == user_id and start <= e.day <= end), key=lambda e: (e.day, e.id))


class ScheduleRepository(InMemoryRepository[WorkSchedule]):
    pass
