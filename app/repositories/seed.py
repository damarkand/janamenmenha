from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from functools import lru_cache

from app.core.security import hash_password
from app.models.domain import Course, Enrollment, HRRequest, Notification, Task, TimeEntry, User, WorkSchedule


@lru_cache(maxsize=32)
def _seed_hash(password: str) -> str:
    return hash_password(password)


def _load(data_dir: Path, name: str) -> list[dict]:
    path = data_dir / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed(data_dir: Path) -> dict[str, list]:
    users = []
    for raw in _load(data_dir, "users"):
        raw = dict(raw)
        raw["password_hash"] = _seed_hash(raw.pop("password"))
        users.append(User(**raw))

    return {
        "users": users,
        "courses": [Course(**c) for c in _load(data_dir, "courses")],
        "enrollments": [Enrollment(**e) for e in _load(data_dir, "enrollments")],
        "requests": [HRRequest(**r) for r in _load(data_dir, "requests")],
        "notifications": [Notification(**n) for n in _load(data_dir, "notifications")],
    }


def _work_days_back(today: date, work_days: list[int], count_days: int) -> list[date]:
    return [today - timedelta(days=i) for i in range(1, count_days + 1)
            if (today - timedelta(days=i)).weekday() in work_days]


def load_work_seed(data_dir: Path, today: date, user_ids: set[str]) -> dict[str, list]:
    def at(days_ago: int) -> datetime:
        d = today - timedelta(days=days_ago)
        return datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc)

    tasks = []
    for raw in _load(data_dir, "tasks"):
        if raw["user_id"] not in user_ids or raw["created_by"] not in user_ids:
            continue
        done_ago = raw.get("completed_days_ago")
        tasks.append(Task(
            id=raw["id"], user_id=raw["user_id"], title=raw["title"], description=raw.get("description", ""),
            category=raw.get("category", "Общее"), status=raw["status"], priority=raw["priority"],
            due_date=today + timedelta(days=raw["due_in_days"]) if raw.get("due_in_days") is not None else None,
            created_by=raw["created_by"], created_at=at(raw.get("created_days_ago", 0)),
            updated_at=at(done_ago if done_ago is not None else 0),
            completed_at=at(done_ago) if done_ago is not None else None,
        ))

    schedules = [WorkSchedule(**s) for s in _load(data_dir, "schedules") if s["id"] in user_ids]
    by_user = {s.id: s for s in schedules}

    entries, n = [], 0
    for uid in sorted(user_ids):
        sched = by_user.get(uid, WorkSchedule(id=uid))
        for day in _work_days_back(today, sched.work_days, 27):
            seed = int(hashlib.md5(f"{uid}:{day}".encode()).hexdigest(), 16)
            if seed % 11 == 0:
                continue
            hours = 8 + ((seed >> 4) % 7 - 3) * 0.5
            n += 1
            entries.append(TimeEntry(id=f"te-{n}", user_id=uid, day=day, hours=hours,
                                     note=NOTES[(seed >> 8) % len(NOTES)], created_at=at((today - day).days)))
    return {"tasks": tasks, "schedules": schedules, "time_entries": entries}


NOTES = ["Текущие задачи", "Встречи и переписка", "Работа с документами", "Плановые работы", "Отчётность"]


def load_holidays(data_dir: Path) -> dict[date, str]:
    return {date.fromisoformat(h["date"]): h["name"] for h in _load(data_dir, "holidays")}
