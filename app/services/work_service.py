from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable

from app.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.domain import (
    EnrollmentStatus, NotificationType, RequestStatus, RequestType, Role, Task, TaskPriority, TaskStatus, TimeEntry,
    User, WorkSchedule, utcnow,
)
from app.services import access
from app.services.notification_service import NotificationService

STATUS_ORDER = {TaskStatus.IN_PROGRESS: 0, TaskStatus.TODO: 1, TaskStatus.DONE: 2}
PRIORITY_ORDER = {TaskPriority.HIGH: 0, TaskPriority.MEDIUM: 1, TaskPriority.LOW: 2}


def hours_per_day(s: WorkSchedule) -> float:
    sh, sm = map(int, s.start_time.split(":"))
    eh, em = map(int, s.end_time.split(":"))
    return max(0.0, ((eh * 60 + em) - (sh * 60 + sm) - s.lunch_minutes) / 60)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


# Задачи
class TaskService:
    def __init__(self, repo, users, notifier: NotificationService, today: Callable[[], date] = date.today):
        self._repo = repo
        self._users = users
        self._notifier = notifier
        self._today = today

    def _user(self, user_id: str) -> User:
        u = self._users.get(user_id)
        if not u:
            raise NotFoundError("Сотрудник не найден")
        return u

    def _can_edit(self, actor: User, task: Task) -> bool:
        return actor.id in (task.user_id, task.created_by) or access.can_manage(actor, self._user(task.user_id))

    def list(self, actor: User, scope: str = "mine", status: TaskStatus | None = None,
             user_id: str | None = None) -> list[Task]:
        if scope == "mine":
            ids = {actor.id}
        elif scope == "team":
            ids = access.team_ids(actor, self._users)
            if user_id:
                if user_id not in ids:
                    raise ForbiddenError("Сотрудник не входит в вашу команду")
                ids = {user_id}
        else:
            raise BusinessRuleError("scope должен быть mine или team")
        items = [t for t in self._repo.for_users(ids) if status is None or t.status == status]
        far = date.max
        return sorted(items, key=lambda t: (STATUS_ORDER[t.status], t.due_date or far, PRIORITY_ORDER[t.priority]))

    def get(self, actor: User, task_id: str) -> Task:
        t = self._repo.get(task_id)
        if not t:
            raise NotFoundError("Задача не найдена")
        owner = self._users.get(t.user_id)
        if actor.id != t.created_by and (not owner or not access.can_view_user(actor, owner)):
            raise NotFoundError("Задача не найдена")
        return t

    def create(self, actor: User, title: str, description: str = "", category: str = "Общее",
               priority: TaskPriority = TaskPriority.MEDIUM, due_date: date | None = None,
               user_id: str | None = None) -> Task:
        target = self._user(user_id) if user_id else actor
        if not access.can_manage(actor, target):
            raise ForbiddenError("Ставить задачи можно себе и своей команде")
        if not title.strip():
            raise BusinessRuleError("Укажите название задачи")
        t = self._repo.add(Task(id=self._repo.next_id(), user_id=target.id, title=title.strip(),
                                description=description.strip(), category=category.strip() or "Общее",
                                priority=TaskPriority(priority), due_date=due_date, created_by=actor.id))
        if target.id != actor.id:
            due = f" до {due_date.strftime('%d.%m.%Y')}" if due_date else ""
            self._notifier.notify(target.id, NotificationType.TASK_ASSIGNED, "Новая задача",
                                  f"{actor.full_name} поставил(а) задачу «{t.title}»{due}", link=f"/tasks/{t.id}")
        return t

    def update(self, actor: User, task_id: str, **fields) -> Task:
        t = self.get(actor, task_id)
        if not self._can_edit(actor, t):
            raise ForbiddenError("Нет прав на изменение задачи")
        for key in ("title", "description", "category", "priority", "due_date"):
            if key in fields and fields[key] is not None:
                value = fields[key].strip() if isinstance(fields[key], str) else fields[key]
                if key == "title" and not value:
                    raise BusinessRuleError("Укажите название задачи")
                if key == "priority":
                    value = TaskPriority(value)
                setattr(t, key, value)
        t.updated_at = utcnow()
        return self._repo.save(t)

    def set_status(self, actor: User, task_id: str, status: TaskStatus) -> Task:
        t = self.get(actor, task_id)
        if not self._can_edit(actor, t):
            raise ForbiddenError("Нет прав на изменение задачи")
        status = TaskStatus(status)
        was_done = t.status == TaskStatus.DONE
        t.status = status
        t.updated_at = utcnow()
        t.completed_at = utcnow() if status == TaskStatus.DONE else None
        self._repo.save(t)
        if status == TaskStatus.DONE and not was_done and t.created_by and t.created_by != actor.id:
            self._notifier.notify(t.created_by, NotificationType.TASK_COMPLETED, "Задача выполнена",
                                  f"{actor.full_name} выполнил(а) задачу «{t.title}»", link=f"/tasks/{t.id}")
        return t

    def delete(self, actor: User, task_id: str) -> None:
        t = self.get(actor, task_id)
        owner = self._user(t.user_id)
        if actor.id != t.created_by and not (actor.id != owner.id and access.can_manage(actor, owner)):
            raise ForbiddenError("Удалить задачу может только её автор или руководитель")
        self._repo.delete(t.id)


# Учёт времени
class TimeService:
    MAX_DAYS_BACK = 60

    def __init__(self, repo, tasks_repo, today: Callable[[], date] = date.today):
        self._repo = repo
        self._tasks = tasks_repo
        self._today = today

    def list(self, actor: User, start: date, end: date) -> list[TimeEntry]:
        if end < start:
            raise BusinessRuleError("Конец периода раньше начала")
        return self._repo.by_user(actor.id, start, end)

    def log(self, actor: User, day: date, hours: float, task_id: str | None = None, note: str = "") -> TimeEntry:
        today = self._today()
        if day > today:
            raise BusinessRuleError("Нельзя отметить часы за будущий день")
        if day < today - timedelta(days=self.MAX_DAYS_BACK):
            raise BusinessRuleError(f"Часы можно отметить не позднее чем за {self.MAX_DAYS_BACK} дней")
        if not 0 < hours <= 24:
            raise BusinessRuleError("Количество часов должно быть от 0 до 24")
        if sum(e.hours for e in self._repo.by_user(actor.id, day, day)) + hours > 24:
            raise BusinessRuleError("За один день нельзя отметить больше 24 часов")
        if task_id:
            task = self._tasks.get(task_id)
            if not task or task.user_id != actor.id:
                raise BusinessRuleError("Можно указать только свою задачу")
        return self._repo.add(TimeEntry(id=self._repo.next_id(), user_id=actor.id, day=day, hours=round(hours, 2),
                                        task_id=task_id, note=note.strip()))

    def delete(self, actor: User, entry_id: str) -> None:
        e = self._repo.get(entry_id)
        if not e or e.user_id != actor.id:
            raise NotFoundError("Запись не найдена")
        self._repo.delete(e.id)


# Рабочий календарь
class ScheduleService:
    def __init__(self, repo, users, requests_repo, time_repo, tasks_repo, holidays: dict[date, str],
                 today: Callable[[], date] = date.today):
        self._repo = repo
        self._users = users
        self._requests = requests_repo
        self._time = time_repo
        self._tasks = tasks_repo
        self._holidays = holidays
        self._today = today

    def _target(self, actor: User, user_id: str | None) -> User:
        target = self._users.get(user_id) if user_id else actor
        if not target:
            raise NotFoundError("Сотрудник не найден")
        access.ensure_can_view_user(actor, target)
        return target

    def schedule_of(self, user_id: str) -> WorkSchedule:
        return self._repo.get(user_id) or WorkSchedule(id=user_id)

    def get(self, actor: User, user_id: str | None = None) -> WorkSchedule:
        return self.schedule_of(self._target(actor, user_id).id)

    def update(self, actor: User, user_id: str, **fields) -> WorkSchedule:
        if actor.role != Role.HR:
            raise ForbiddenError("График работы меняет HR")
        target = self._target(actor, user_id)
        s = self.schedule_of(target.id)
        for key, value in fields.items():
            if value is not None:
                setattr(s, key, value)
        if not s.work_days or any(d not in range(7) for d in s.work_days):
            raise BusinessRuleError("Рабочие дни — числа от 0 (пн) до 6 (вс)")
        if hours_per_day(s) <= 0:
            raise BusinessRuleError("Конец рабочего дня должен быть позже начала с учётом обеда")
        s.work_days = sorted(set(s.work_days))
        return self._repo.save(s)

    def day_types(self, user_id: str, start: date, end: date) -> dict[date, str]:
        sched = self.schedule_of(user_id)
        vacations, pending = set(), set()
        for r in self._requests.by_user(user_id, RequestType.VACATION,
                                        {RequestStatus.APPROVED, RequestStatus.PENDING}):
            if not r.vacation:
                continue
            d = max(r.vacation.start_date, start)
            while d <= min(r.vacation.end_date, end):
                (vacations if r.status == RequestStatus.APPROVED else pending).add(d)
                d += timedelta(days=1)
        result, d = {}, start
        while d <= end:
            if d in vacations:
                result[d] = "vacation"
            elif d in self._holidays:
                result[d] = "holiday"
            elif d.weekday() not in sched.work_days:
                result[d] = "weekend"
            elif d in pending:
                result[d] = "vacation_pending"
            else:
                result[d] = "workday"
            d += timedelta(days=1)
        return result

    def calendar(self, actor: User, month: str | None = None, user_id: str | None = None) -> dict:
        target = self._target(actor, user_id)
        today = self._today()
        try:
            year, mon = map(int, (month or today.strftime("%Y-%m")).split("-"))
            start = date(year, mon, 1)
        except ValueError:
            raise BusinessRuleError("Месяц указывается в формате ГГГГ-ММ")
        end = date(year, mon, calendar.monthrange(year, mon)[1])
        sched = self.schedule_of(target.id)
        plan = hours_per_day(sched)
        types = self.day_types(target.id, start, end)
        logged = Counter()
        for e in self._time.by_user(target.id, start, end):
            logged[e.day] += e.hours
        due = {}
        for t in self._tasks.for_users({target.id}):
            if t.due_date and start <= t.due_date <= end:
                due.setdefault(t.due_date, []).append({"id": t.id, "title": t.title, "status": t.status.value})
        days = [{
            "date": d, "type": types[d], "holiday": self._holidays.get(d), "is_today": d == today,
            "planned_hours": plan if types[d] in ("workday", "vacation_pending") else 0,
            "logged_hours": round(logged.get(d, 0), 2), "tasks_due": due.get(d, []),
        } for d in sorted(types)]
        return {
            "month": start.strftime("%Y-%m"), "user_id": target.id, "schedule": sched, "hours_per_day": plan,
            "days": days,
            "summary": {
                "workdays": sum(1 for x in days if x["planned_hours"] > 0),
                "planned_hours": round(sum(x["planned_hours"] for x in days), 2),
                "planned_to_date": round(sum(x["planned_hours"] for x in days if x["date"] <= today), 2),
                "logged_hours": round(sum(x["logged_hours"] for x in days), 2),
                "vacation_days": sum(1 for x in days if x["type"] == "vacation"),
                "holidays": sum(1 for x in days if x["type"] == "holiday"),
            },
        }


# Дашборд
class DashboardService:
    def __init__(self, users, tasks: TaskService, tasks_repo, time_repo, schedules: ScheduleService, enrollments,
                 courses, requests_repo, holidays: dict[date, str], today: Callable[[], date] = date.today):
        self._users = users
        self._task_service = tasks
        self._tasks = tasks_repo
        self._time = time_repo
        self._schedules = schedules
        self._enrollments = enrollments
        self._courses = courses
        self._requests = requests_repo
        self._holidays = holidays
        self._today = today

    def _stats(self, user: User) -> dict:
        today = self._today()
        tasks = self._tasks.for_users({user.id})
        open_tasks = [t for t in tasks if t.status != TaskStatus.DONE]
        overdue = [t for t in open_tasks if t.due_date and t.due_date < today]
        ws = week_start(today)
        types = self._schedules.day_types(user.id, ws, today)
        plan = hours_per_day(self._schedules.schedule_of(user.id))
        planned_week = sum(plan for d, kind in types.items() if kind in ("workday", "vacation_pending"))
        hours_week = sum(e.hours for e in self._time.by_user(user.id, ws, today))
        enr = self._enrollments.by_user(user.id)
        done_30 = [t for t in tasks if t.completed_at and t.completed_at.date() >= today - timedelta(days=30)]
        return {
            "open_tasks": len(open_tasks), "overdue_tasks": len(overdue), "done_30d": len(done_30),
            "hours_week": round(hours_week, 2), "planned_week": round(planned_week, 2),
            "courses_done": sum(1 for e in enr if e.status == EnrollmentStatus.COMPLETED),
            "courses_total": len(enr), "vacation_days_left": user.vacation_days_left,
        }

    def me(self, actor: User) -> dict:
        today = self._today()
        tasks = self._tasks.for_users({actor.id})
        stats = self._stats(actor)

        start14 = today - timedelta(days=13)
        types = self._schedules.day_types(actor.id, start14, today)
        plan = hours_per_day(self._schedules.schedule_of(actor.id))
        logged = Counter()
        for e in self._time.by_user(actor.id, start14, today):
            logged[e.day] += e.hours
        hours_by_day = [{"date": d, "logged": round(logged.get(d, 0), 2),
                         "planned": plan if kind in ("workday", "vacation_pending") else 0, "type": kind}
                        for d, kind in sorted(types.items())]

        first_week = week_start(today) - timedelta(weeks=7)
        done_weeks = Counter(week_start(t.completed_at.date()) for t in tasks
                             if t.completed_at and t.completed_at.date() >= first_week)
        tasks_done_by_week = [{"week_start": first_week + timedelta(weeks=i),
                               "count": done_weeks.get(first_week + timedelta(weeks=i), 0)} for i in range(8)]

        learning = []
        for e in self._enrollments.by_user(actor.id):
            c = self._courses.get(e.course_id)
            if c:
                learning.append({"course_id": c.id, "title": c.title, "progress": e.progress,
                                 "status": e.status.value})

        upcoming = [t for t in self._task_service.list(actor, "mine")
                    if t.status != TaskStatus.DONE and t.due_date][:5]
        next_holiday = next(({"date": d, "name": n} for d, n in sorted(self._holidays.items()) if d >= today), None)
        vacations = sorted((r for r in self._requests.by_user(actor.id, RequestType.VACATION, {RequestStatus.APPROVED})
                            if r.vacation and r.vacation.end_date >= today), key=lambda r: r.vacation.start_date)
        pending_requests = len(self._requests.by_user(actor.id, statuses={RequestStatus.PENDING}))

        return {
            "today": today,
            "cards": {**stats, "pending_requests": pending_requests},
            "charts": {
                "hours_by_day": hours_by_day,
                "tasks_by_status": {s.value: sum(1 for t in tasks if t.status == s) for s in TaskStatus},
                "tasks_done_by_week": tasks_done_by_week,
                "tasks_by_category": [{"category": k, "count": v}
                                      for k, v in Counter(t.category for t in tasks).most_common()],
                "learning": learning,
            },
            "upcoming_tasks": upcoming,
            "next_holiday": next_holiday,
            "next_vacation": ({"start_date": vacations[0].vacation.start_date, "end_date": vacations[0].vacation.end_date,
                               "days": vacations[0].vacation.days} if vacations else None),
        }

    def team(self, actor: User) -> dict:
        ids = access.team_ids(actor, self._users)
        members = []
        for u in sorted(self._users.list(lambda x: x.id in ids), key=lambda x: x.full_name):
            members.append({"user": {"id": u.id, "full_name": u.full_name}, "position": u.position,
                            "department": u.department, **self._stats(u)})
        pending = [r for r in self._requests.for_users(ids) if r.status == RequestStatus.PENDING]
        return {
            "members": members,
            "totals": {
                "members": len(members),
                "open_tasks": sum(m["open_tasks"] for m in members),
                "overdue_tasks": sum(m["overdue_tasks"] for m in members),
                "hours_week": round(sum(m["hours_week"] for m in members), 2),
                "planned_week": round(sum(m["planned_week"] for m in members), 2),
                "pending_requests": len(pending),
            },
        }
