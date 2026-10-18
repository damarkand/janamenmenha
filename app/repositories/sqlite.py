from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Generic, TypeVar

import database as db
from app.core.config import Settings
from app.core.security import hash_password
from app.models.domain import (
    AdvanceDetails, Course, Enrollment, EnrollmentStatus, Escalation, HistoryEntry, HRRequest, Notification,
    NotificationType, Question, RequestStatus, RequestType, Role, Task, TimeEntry, User, VacationDetails,
    WorkSchedule,
)
from app.repositories.seed import load_seed, load_work_seed

log = logging.getLogger(__name__)
T = TypeVar("T")

ROLE_TO_DB = {Role.EMPLOYEE: "worker", Role.MANAGER: "manager", Role.HR: "hr"}
ROLE_FROM_DB = {v: k for k, v in ROLE_TO_DB.items()}
ENROLLMENT_TO_DB = {EnrollmentStatus.NOT_STARTED: "assigned", EnrollmentStatus.IN_PROGRESS: "in_progress",
                    EnrollmentStatus.COMPLETED: "completed"}
ENROLLMENT_FROM_DB = {v: k for k, v in ENROLLMENT_TO_DB.items()}

API_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_user_credentials (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_user_hr (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    personnel_number TEXT,
    salary           INTEGER
);
CREATE TABLE IF NOT EXISTS api_request_history (
    id          INTEGER PRIMARY KEY,
    request_id  INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    comment     TEXT
);
CREATE TABLE IF NOT EXISTS api_request_refs (
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    PRIMARY KEY (request_id, key)
);
CREATE TABLE IF NOT EXISTS api_course_meta (
    course_id     INTEGER PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    category      TEXT,
    duration_min  INTEGER,
    passing_score INTEGER,
    mandatory     INTEGER
);
CREATE TABLE IF NOT EXISTS api_course_questions (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    code          TEXT NOT NULL,
    text          TEXT NOT NULL,
    options       TEXT NOT NULL,
    correct_index INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS api_enrollment_meta (
    user_course_id INTEGER PRIMARY KEY REFERENCES user_courses(id) ON DELETE CASCADE,
    best_score     INTEGER,
    attempts       INTEGER NOT NULL DEFAULT 0,
    assigned_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_at    TEXT,
    due_date       TEXT,
    completed_at   TEXT
);
CREATE TABLE IF NOT EXISTS api_notification_meta (
    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id) ON DELETE CASCADE,
    type            TEXT,
    title           TEXT,
    link            TEXT
);
CREATE TABLE IF NOT EXISTS api_escalations (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    context     TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    answer      TEXT,
    answered_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    answered_at TEXT
);
CREATE TABLE IF NOT EXISTS api_tasks (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT 'Общее',
    status       TEXT NOT NULL DEFAULT 'todo',
    priority     TEXT NOT NULL DEFAULT 'medium',
    due_date     TEXT,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS api_time_entries (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day        TEXT NOT NULL,
    hours      REAL NOT NULL CHECK (hours > 0 AND hours <= 24),
    task_id    INTEGER REFERENCES api_tasks(id) ON DELETE SET NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_user_schedule (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    work_days     TEXT NOT NULL,
    start_time    TEXT NOT NULL,
    end_time      TEXT NOT NULL,
    lunch_minutes INTEGER NOT NULL,
    work_format   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_tasks_user ON api_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_api_time_user_day ON api_time_entries(user_id, day);
CREATE INDEX IF NOT EXISTS idx_api_history_request ON api_request_history(request_id);
CREATE INDEX IF NOT EXISTS idx_api_questions_course ON api_course_questions(course_id, position);
"""


# Преобразования
def to_int(item_id, prefix: str) -> int | None:
    if item_id is None:
        return None
    s = str(item_id)
    if s.startswith(prefix + "-"):
        s = s[len(prefix) + 1:]
    return int(s) if s.isdigit() else None


def to_id(n: int | None, prefix: str) -> str | None:
    return f"{prefix}-{n}" if n is not None else None


def ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@lru_cache(maxsize=32)
def _demo_hash(password: str) -> str:
    return hash_password(password)


# Базовый репозиторий
class _SqliteRepository(Generic[T]):
    table = ""
    prefix = ""

    def next_id(self) -> str:
        with db.get_connection() as conn:
            n = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {self.table}").fetchone()[0]
        return to_id(n, self.prefix)

    def get(self, item_id: str) -> T | None:
        n = to_int(item_id, self.prefix)
        if n is None:
            return None
        items = self._load(f"WHERE t.id = ?", (n,))
        return items[0] if items else None

    def list(self, predicate: Callable[[T], bool] | None = None) -> list[T]:
        return [i for i in self._load() if predicate is None or predicate(i)]

    def _load(self, where: str = "", params: tuple = ()) -> list[T]:
        raise NotImplementedError


# Сотрудники
class SqliteUserRepository(_SqliteRepository[User]):
    table, prefix = "users", "u"

    def __init__(self, default_salary: int):
        self._default_salary = default_salary

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT t.*, c.password_hash, h.personnel_number, h.salary
                FROM users t
                LEFT JOIN api_user_credentials c ON c.user_id = t.id
                LEFT JOIN api_user_hr h ON h.user_id = t.id
                {where} ORDER BY t.id""", params).fetchall()
        return [User(
            id=to_id(r["id"], "u"), email=r["email"] or "", password_hash=r["password_hash"] or "",
            role=ROLE_FROM_DB[r["role"]], full_name=r["full_name"], company=r["company"], position=r["position"],
            department=r["department"], manager_id=to_id(r["manager_id"], "u"), hire_date=parse_date(r["hire_date"]),
            vacation_days_left=r["vacation_days_left"],
            salary=r["salary"] if r["salary"] is not None else self._default_salary,
            personnel_number=r["personnel_number"] or f"{r['id']:05d}",
        ) for r in rows]

    def get_by_email(self, email: str) -> User | None:
        items = self._load("WHERE lower(t.email) = ?", (email.strip().lower(),))
        return items[0] if items else None

    def direct_reports(self, manager_id: str) -> list[User]:
        return self._load("WHERE t.manager_id = ?", (to_int(manager_id, "u"),))

    def by_role(self, role: Role) -> list[User]:
        return self._load("WHERE t.role = ?", (ROLE_TO_DB[role],))

    def add(self, user: User) -> User:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO users (full_name, company, position, department, manager_id, hire_date, "
                "vacation_days_left, role, email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._columns(user))
            user.id = to_id(cur.lastrowid, "u")
            self._save_ext(conn, user)
        return user

    def save(self, user: User) -> User:
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE users SET full_name=?, company=?, position=?, department=?, manager_id=?, hire_date=?, "
                "vacation_days_left=?, role=?, email=? WHERE id=?",
                (*self._columns(user), to_int(user.id, "u")))
            self._save_ext(conn, user)
        return user

    @staticmethod
    def _columns(u: User) -> tuple:
        return (u.full_name, u.company, u.position, u.department, to_int(u.manager_id, "u"),
                u.hire_date.isoformat() if u.hire_date else None, u.vacation_days_left, ROLE_TO_DB[u.role],
                u.email or None)

    @staticmethod
    def _save_ext(conn, u: User) -> None:
        uid = to_int(u.id, "u")
        if u.password_hash:
            conn.execute("INSERT INTO api_user_credentials (user_id, password_hash) VALUES (?, ?) "
                         "ON CONFLICT(user_id) DO UPDATE SET password_hash = excluded.password_hash",
                         (uid, u.password_hash))
        conn.execute("INSERT INTO api_user_hr (user_id, personnel_number, salary) VALUES (?, ?, ?) "
                     "ON CONFLICT(user_id) DO UPDATE SET personnel_number = excluded.personnel_number, "
                     "salary = excluded.salary", (uid, u.personnel_number, u.salary))


# Заявки
class SqliteRequestRepository(_SqliteRepository[HRRequest]):
    table, prefix = "requests", "req"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"SELECT t.* FROM requests t {where} ORDER BY t.id", params).fetchall()
            ids = [r["id"] for r in rows]
            history, refs = {}, {}
            if ids:
                marks = ",".join("?" * len(ids))
                for h in conn.execute(f"SELECT * FROM api_request_history WHERE request_id IN ({marks}) "
                                      f"ORDER BY id", ids):
                    history.setdefault(h["request_id"], []).append(h)
                for x in conn.execute(f"SELECT * FROM api_request_refs WHERE request_id IN ({marks})", ids):
                    refs.setdefault(x["request_id"], {})[x["key"]] = x["value"]
        return [self._to_domain(r, history.get(r["id"], []), refs.get(r["id"], {})) for r in rows]

    @staticmethod
    def _to_domain(r, history_rows, refs) -> HRRequest:
        type_ = RequestType(r["request_type"])
        created, decided = parse_ts(r["created_at"]), parse_ts(r["decided_at"])
        status = RequestStatus(r["status"])
        text = r["details"] or None
        vacation = advance = None
        if type_ == RequestType.VACATION and r["start_date"] and r["end_date"]:
            start, end = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])
            vacation = VacationDetails(start_date=start, end_date=end, days=r["days"] or (end - start).days + 1,
                                       comment=text)
        elif type_ == RequestType.ADVANCE:
            advance = AdvanceDetails(amount=int(round(r["amount"] or 0)), reason=text)

        if history_rows:
            history = [HistoryEntry(at=parse_ts(h["at"]), actor_id=to_id(h["actor_id"], "u") or "",
                                    action=h["action"], from_status=h["from_status"], to_status=h["to_status"],
                                    comment=h["comment"]) for h in history_rows]
        else:
            history = [HistoryEntry(at=created, actor_id=to_id(r["user_id"], "u"), action="created",
                                    to_status=RequestStatus.PENDING)]
            if status != RequestStatus.PENDING:
                actor = r["approver_id"] if status != RequestStatus.CANCELLED else r["user_id"]
                history.append(HistoryEntry(at=decided or created, actor_id=to_id(actor, "u") or "",
                                            action=status.value, from_status=RequestStatus.PENDING,
                                            to_status=status, comment=r["decision_comment"]))
        return HRRequest(
            id=to_id(r["id"], "req"), type=type_, user_id=to_id(r["user_id"], "u"), status=status,
            created_at=created, updated_at=decided or created, vacation=vacation, advance=advance,
            comment=text if type_ in (RequestType.SICK_LEAVE, RequestType.OTHER) else None,
            decided_by=to_id(r["approver_id"], "u"), external_refs=refs, history=history)

    def for_users(self, user_ids: set[str]) -> list[HRRequest]:
        ids = [to_int(u, "u") for u in user_ids]
        if not ids:
            return []
        return self._load(f"WHERE t.user_id IN ({','.join('?' * len(ids))})", tuple(ids))

    def by_user(self, user_id: str, type_: RequestType | None = None,
                statuses: set[RequestStatus] | None = None) -> list[HRRequest]:
        return [r for r in self._load("WHERE t.user_id = ?", (to_int(user_id, "u"),))
                if (type_ is None or r.type == type_) and (statuses is None or r.status in statuses)]

    @staticmethod
    def _columns(r: HRRequest) -> dict:
        v, a = r.vacation, r.advance
        details = (v.comment if v else a.reason if a else r.comment) or ""
        decision = next((h.comment for h in reversed(r.history)
                         if h.action in ("approved", "rejected")), None)
        return {
            "user_id": to_int(r.user_id, "u"), "request_type": r.type.value, "details": details,
            "start_date": v.start_date.isoformat() if v else None, "end_date": v.end_date.isoformat() if v else None,
            "days": v.days if v else None, "amount": float(a.amount) if a else None, "status": r.status.value,
            "approver_id": to_int(r.decided_by, "u"), "decision_comment": decision,
            "decided_at": ts(r.updated_at) if r.status != RequestStatus.PENDING else None,
        }

    def add(self, r: HRRequest) -> HRRequest:
        cols = {**self._columns(r), "created_at": ts(r.created_at)}
        with db.get_connection() as conn:
            cur = conn.execute(f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               tuple(cols.values()))
            r.id = to_id(cur.lastrowid, "req")
            self._save_ext(conn, r)
        return r

    def save(self, r: HRRequest) -> HRRequest:
        cols = self._columns(r)
        with db.get_connection() as conn:
            conn.execute(f"UPDATE requests SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                         (*cols.values(), to_int(r.id, "req")))
            self._save_ext(conn, r)
        return r

    @staticmethod
    def _save_ext(conn, r: HRRequest) -> None:
        rid = to_int(r.id, "req")
        stored = conn.execute("SELECT COUNT(*) FROM api_request_history WHERE request_id = ?", (rid,)).fetchone()[0]
        for h in r.history[stored:]:
            conn.execute("INSERT INTO api_request_history (request_id, at, actor_id, action, from_status, "
                         "to_status, comment) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (rid, ts(h.at), to_int(h.actor_id, "u"), h.action,
                          h.from_status.value if h.from_status else None, h.to_status.value, h.comment))
        for k, v in r.external_refs.items():
            conn.execute("INSERT INTO api_request_refs (request_id, key, value) VALUES (?, ?, ?) "
                         "ON CONFLICT(request_id, key) DO UPDATE SET value = excluded.value", (rid, k, v))


# Курсы
class SqliteCourseRepository(_SqliteRepository[Course]):
    table, prefix = "courses", "c"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT t.*, m.category, m.duration_min, m.passing_score, m.mandatory
                FROM courses t LEFT JOIN api_course_meta m ON m.course_id = t.id
                {where} ORDER BY t.id""", params).fetchall()
            questions = {}
            for q in conn.execute("SELECT * FROM api_course_questions ORDER BY course_id, position"):
                questions.setdefault(q["course_id"], []).append(
                    Question(id=q["code"], text=q["text"], options=json.loads(q["options"]),
                             correct_index=q["correct_index"]))
        return [Course(
            id=to_id(r["id"], "c"), title=r["title"], description=r["description"] or "",
            category=r["category"] or "general", duration_min=r["duration_min"] or 0,
            passing_score=r["passing_score"] if r["passing_score"] is not None else 70,
            mandatory=bool(r["mandatory"]), material_link=r["material_link"],
            questions=questions.get(r["id"], []),
        ) for r in rows]

    def add(self, c: Course) -> Course:
        with db.get_connection() as conn:
            cur = conn.execute("INSERT INTO courses (title, description, material_link) VALUES (?, ?, ?)",
                               (c.title, c.description, c.material_link))
            c.id = to_id(cur.lastrowid, "c")
            write_course_ext(conn, cur.lastrowid, c)
        return c

    def save(self, c: Course) -> Course:
        cid = to_int(c.id, "c")
        with db.get_connection() as conn:
            conn.execute("UPDATE courses SET title=?, description=?, material_link=? WHERE id=?",
                         (c.title, c.description, c.material_link, cid))
            conn.execute("DELETE FROM api_course_questions WHERE course_id = ?", (cid,))
            write_course_ext(conn, cid, c)
        return c


def write_course_ext(conn, course_id: int, c: Course) -> None:
    conn.execute("INSERT INTO api_course_meta (course_id, category, duration_min, passing_score, mandatory) "
                 "VALUES (?, ?, ?, ?, ?) ON CONFLICT(course_id) DO UPDATE SET category=excluded.category, "
                 "duration_min=excluded.duration_min, passing_score=excluded.passing_score, "
                 "mandatory=excluded.mandatory",
                 (course_id, c.category, c.duration_min, c.passing_score, int(c.mandatory)))
    for pos, q in enumerate(c.questions):
        conn.execute("INSERT INTO api_course_questions (course_id, position, code, text, options, correct_index) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (course_id, pos, q.id, q.text, json.dumps(q.options, ensure_ascii=False), q.correct_index))


# Записи на курсы
class SqliteEnrollmentRepository(_SqliteRepository[Enrollment]):
    table, prefix = "user_courses", "enr"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT t.*, m.best_score, m.attempts, m.assigned_by, m.assigned_at, m.due_date, m.completed_at
                FROM user_courses t LEFT JOIN api_enrollment_meta m ON m.user_course_id = t.id
                {where} ORDER BY t.id""", params).fetchall()
        return [Enrollment(
            id=to_id(r["id"], "enr"), user_id=to_id(r["user_id"], "u"), course_id=to_id(r["course_id"], "c"),
            status=ENROLLMENT_FROM_DB[r["status"]], progress=r["progress"], best_score=r["best_score"],
            attempts=r["attempts"] or 0, assigned_by=to_id(r["assigned_by"], "u"),
            assigned_at=parse_ts(r["assigned_at"]), due_date=parse_date(r["due_date"]),
            completed_at=parse_ts(r["completed_at"]),
        ) for r in rows]

    def find(self, user_id: str, course_id: str) -> Enrollment | None:
        items = self._load("WHERE t.user_id = ? AND t.course_id = ?", (to_int(user_id, "u"), to_int(course_id, "c")))
        return items[0] if items else None

    def by_user(self, user_id: str) -> list[Enrollment]:
        return self._load("WHERE t.user_id = ?", (to_int(user_id, "u"),))

    def add(self, e: Enrollment) -> Enrollment:
        with db.get_connection() as conn:
            cur = conn.execute("INSERT INTO user_courses (user_id, course_id, progress, status) VALUES (?, ?, ?, ?)",
                               (to_int(e.user_id, "u"), to_int(e.course_id, "c"), e.progress,
                                ENROLLMENT_TO_DB[e.status]))
            e.id = to_id(cur.lastrowid, "enr")
            write_enrollment_ext(conn, cur.lastrowid, e)
        return e

    def save(self, e: Enrollment) -> Enrollment:
        eid = to_int(e.id, "enr")
        with db.get_connection() as conn:
            conn.execute("UPDATE user_courses SET progress = ?, status = ? WHERE id = ?",
                         (e.progress, ENROLLMENT_TO_DB[e.status], eid))
            write_enrollment_ext(conn, eid, e)
        return e


def write_enrollment_ext(conn, enrollment_id: int, e: Enrollment) -> None:
    conn.execute(
        "INSERT INTO api_enrollment_meta (user_course_id, best_score, attempts, assigned_by, assigned_at, due_date, "
        "completed_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_course_id) DO UPDATE SET "
        "best_score=excluded.best_score, attempts=excluded.attempts, assigned_by=excluded.assigned_by, "
        "assigned_at=excluded.assigned_at, due_date=excluded.due_date, completed_at=excluded.completed_at",
        (enrollment_id, e.best_score, e.attempts, to_int(e.assigned_by, "u"), ts(e.assigned_at),
         e.due_date.isoformat() if e.due_date else None, ts(e.completed_at)))


# Уведомления
class SqliteNotificationRepository(_SqliteRepository[Notification]):
    table, prefix = "notifications", "n"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"""
                SELECT t.*, m.type, m.title, m.link
                FROM notifications t LEFT JOIN api_notification_meta m ON m.notification_id = t.id
                {where} ORDER BY t.created_at DESC, t.id DESC""", params).fetchall()
        return [Notification(
            id=to_id(r["id"], "n"), user_id=to_id(r["user_id"], "u"),
            type=NotificationType(r["type"]) if r["type"] else NotificationType.GENERAL,
            title=r["title"] or "Уведомление", message=r["message"], link=r["link"], read=bool(r["is_read"]),
            created_at=parse_ts(r["created_at"]),
        ) for r in rows]

    def by_user(self, user_id: str) -> list[Notification]:
        return self._load("WHERE t.user_id = ?", (to_int(user_id, "u"),))

    def add(self, n: Notification) -> Notification:
        with db.get_connection() as conn:
            cur = conn.execute("INSERT INTO notifications (user_id, message, created_at, is_read) VALUES (?, ?, ?, ?)",
                               (to_int(n.user_id, "u"), n.message, ts(n.created_at), int(n.read)))
            n.id = to_id(cur.lastrowid, "n")
            write_notification_ext(conn, cur.lastrowid, n)
        return n

    def save(self, n: Notification) -> Notification:
        with db.get_connection() as conn:
            conn.execute("UPDATE notifications SET message = ?, is_read = ? WHERE id = ?",
                         (n.message, int(n.read), to_int(n.id, "n")))
        return n


def write_notification_ext(conn, notification_id: int, n: Notification) -> None:
    conn.execute("INSERT OR REPLACE INTO api_notification_meta (notification_id, type, title, link) VALUES (?, ?, ?, ?)",
                 (notification_id, n.type.value, n.title, n.link))


# Обращения к HR
class SqliteEscalationRepository(_SqliteRepository[Escalation]):
    table, prefix = "api_escalations", "esc"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"SELECT t.* FROM api_escalations t {where} ORDER BY t.id", params).fetchall()
        return [Escalation(
            id=to_id(r["id"], "esc"), user_id=to_id(r["user_id"], "u"), question=r["question"], context=r["context"],
            status=r["status"], created_at=parse_ts(r["created_at"]), answer=r["answer"],
            answered_by=to_id(r["answered_by"], "u"), answered_at=parse_ts(r["answered_at"]),
        ) for r in rows]

    def _columns(self, e: Escalation) -> tuple:
        return (to_int(e.user_id, "u"), e.question, e.context, e.status, ts(e.created_at), e.answer,
                to_int(e.answered_by, "u"), ts(e.answered_at))

    def add(self, e: Escalation) -> Escalation:
        with db.get_connection() as conn:
            cur = conn.execute("INSERT INTO api_escalations (user_id, question, context, status, created_at, answer, "
                               "answered_by, answered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", self._columns(e))
            e.id = to_id(cur.lastrowid, "esc")
        return e

    def save(self, e: Escalation) -> Escalation:
        with db.get_connection() as conn:
            conn.execute("UPDATE api_escalations SET user_id=?, question=?, context=?, status=?, created_at=?, "
                         "answer=?, answered_by=?, answered_at=? WHERE id=?", (*self._columns(e), to_int(e.id, "esc")))
        return e


# Задачи
class SqliteTaskRepository(_SqliteRepository[Task]):
    table, prefix = "api_tasks", "t"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"SELECT t.* FROM api_tasks t {where} ORDER BY t.id", params).fetchall()
        return [Task(
            id=to_id(r["id"], "t"), user_id=to_id(r["user_id"], "u"), title=r["title"], description=r["description"],
            category=r["category"], status=r["status"], priority=r["priority"], due_date=parse_date(r["due_date"]),
            created_by=to_id(r["created_by"], "u") or "", created_at=parse_ts(r["created_at"]),
            updated_at=parse_ts(r["updated_at"]), completed_at=parse_ts(r["completed_at"]),
        ) for r in rows]

    def for_users(self, user_ids: set[str]) -> list[Task]:
        ids = [to_int(u, "u") for u in user_ids]
        if not ids:
            return []
        return self._load(f"WHERE t.user_id IN ({','.join('?' * len(ids))})", tuple(ids))

    @staticmethod
    def _columns(t: Task) -> dict:
        return {"user_id": to_int(t.user_id, "u"), "title": t.title, "description": t.description,
                "category": t.category, "status": t.status.value, "priority": t.priority.value,
                "due_date": t.due_date.isoformat() if t.due_date else None, "created_by": to_int(t.created_by, "u"),
                "created_at": ts(t.created_at), "updated_at": ts(t.updated_at), "completed_at": ts(t.completed_at)}

    def add(self, t: Task, keep_id: bool = False) -> Task:
        cols = self._columns(t)
        if keep_id:
            cols = {"id": to_int(t.id, "t"), **cols}
        with db.get_connection() as conn:
            cur = conn.execute(f"INSERT INTO api_tasks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               tuple(cols.values()))
            t.id = to_id(cur.lastrowid, "t")
        return t

    def save(self, t: Task) -> Task:
        cols = self._columns(t)
        with db.get_connection() as conn:
            conn.execute(f"UPDATE api_tasks SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                         (*cols.values(), to_int(t.id, "t")))
        return t

    def delete(self, task_id: str) -> None:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM api_tasks WHERE id = ?", (to_int(task_id, "t"),))


# Учёт времени
class SqliteTimeEntryRepository(_SqliteRepository[TimeEntry]):
    table, prefix = "api_time_entries", "te"

    def _load(self, where="", params=()):
        with db.get_connection() as conn:
            rows = conn.execute(f"SELECT t.* FROM api_time_entries t {where} ORDER BY t.day, t.id", params).fetchall()
        return [TimeEntry(id=to_id(r["id"], "te"), user_id=to_id(r["user_id"], "u"), day=date.fromisoformat(r["day"]),
                          hours=r["hours"], task_id=to_id(r["task_id"], "t"), note=r["note"],
                          created_at=parse_ts(r["created_at"])) for r in rows]

    def by_user(self, user_id: str, start: date, end: date) -> list[TimeEntry]:
        return self._load("WHERE t.user_id = ? AND t.day BETWEEN ? AND ?",
                          (to_int(user_id, "u"), start.isoformat(), end.isoformat()))

    def add(self, e: TimeEntry) -> TimeEntry:
        with db.get_connection() as conn:
            cur = conn.execute("INSERT INTO api_time_entries (user_id, day, hours, task_id, note, created_at) "
                               "VALUES (?, ?, ?, ?, ?, ?)",
                               (to_int(e.user_id, "u"), e.day.isoformat(), e.hours, to_int(e.task_id, "t"), e.note,
                                ts(e.created_at)))
            e.id = to_id(cur.lastrowid, "te")
        return e

    save = add

    def delete(self, entry_id: str) -> None:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM api_time_entries WHERE id = ?", (to_int(entry_id, "te"),))


# График работы
class SqliteScheduleRepository:
    def get(self, user_id: str) -> WorkSchedule | None:
        with db.get_connection() as conn:
            r = conn.execute("SELECT * FROM api_user_schedule WHERE user_id = ?", (to_int(user_id, "u"),)).fetchone()
        if not r:
            return None
        return WorkSchedule(id=user_id, work_days=json.loads(r["work_days"]), start_time=r["start_time"],
                            end_time=r["end_time"], lunch_minutes=r["lunch_minutes"], work_format=r["work_format"])

    def save(self, s: WorkSchedule) -> WorkSchedule:
        with db.get_connection() as conn:
            write_schedule(conn, s)
        return s

    add = save


def write_schedule(conn, s: WorkSchedule) -> None:
    conn.execute("INSERT OR REPLACE INTO api_user_schedule (user_id, work_days, start_time, end_time, lunch_minutes, "
                 "work_format) VALUES (?, ?, ?, ?, ?, ?)",
                 (to_int(s.id, "u"), json.dumps(s.work_days), s.start_time, s.end_time, s.lunch_minutes, s.work_format))


# Подготовка базы
def seed_work_data(data_dir: Path, today: date) -> None:
    with db.get_connection() as conn:
        has_tasks = conn.execute("SELECT COUNT(*) FROM api_tasks").fetchone()[0]
        has_time = conn.execute("SELECT COUNT(*) FROM api_time_entries").fetchone()[0]
        user_ids = {to_id(r[0], "u") for r in conn.execute("SELECT id FROM users")}
    if has_tasks or has_time or not user_ids:
        return
    work = load_work_seed(data_dir, today, user_ids)
    tasks = SqliteTaskRepository()
    for t in work["tasks"]:
        tasks.add(t, keep_id=True)
    with db.get_connection() as conn:
        for s in work["schedules"]:
            write_schedule(conn, s)
        conn.executemany("INSERT INTO api_time_entries (user_id, day, hours, task_id, note, created_at) "
                         "VALUES (?, ?, ?, NULL, ?, ?)",
                         [(to_int(e.user_id, "u"), e.day.isoformat(), e.hours, e.note, ts(e.created_at))
                          for e in work["time_entries"]])


def init_storage(settings: Settings, today: date | None = None) -> None:
    db.DB_PATH = Path(settings.db_path)
    db.init_db()
    with db.get_connection() as conn:
        conn.executescript(API_SCHEMA)
    with db.get_connection() as conn:
        empty = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if empty:
        seed_from_json(settings.data_dir)
        log.info("База пуста — загружены демо-данные из %s", settings.data_dir)
    ensure_credentials(settings.demo_password)
    seed_work_data(settings.data_dir, today or date.today())


def seed_from_json(data_dir: Path) -> None:
    seed = load_seed(data_dir)
    qa_path = Path(data_dir) / "knowledge_base_qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else []
    with db.get_connection() as conn:
        for u in seed["users"]:
            conn.execute("INSERT INTO users (id, full_name, company, position, department, manager_id, hire_date, "
                         "vacation_days_left, role, email) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                         (to_int(u.id, "u"), u.full_name, u.company, u.position, u.department,
                          u.hire_date.isoformat() if u.hire_date else None, u.vacation_days_left,
                          ROLE_TO_DB[u.role], u.email))
        for u in seed["users"]:
            conn.execute("UPDATE users SET manager_id = ? WHERE id = ?", (to_int(u.manager_id, "u"), to_int(u.id, "u")))
            SqliteUserRepository._save_ext(conn, u)

        for c in seed["courses"]:
            conn.execute("INSERT INTO courses (id, title, description, material_link) VALUES (?, ?, ?, ?)",
                         (to_int(c.id, "c"), c.title, c.description, c.material_link))
            write_course_ext(conn, to_int(c.id, "c"), c)

        for e in seed["enrollments"]:
            conn.execute("INSERT INTO user_courses (id, user_id, course_id, progress, status) VALUES (?, ?, ?, ?, ?)",
                         (to_int(e.id, "enr"), to_int(e.user_id, "u"), to_int(e.course_id, "c"), e.progress,
                          ENROLLMENT_TO_DB[e.status]))
            write_enrollment_ext(conn, to_int(e.id, "enr"), e)

        for r in seed["requests"]:
            cols = {"id": to_int(r.id, "req"), **SqliteRequestRepository._columns(r), "created_at": ts(r.created_at)}
            conn.execute(f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         tuple(cols.values()))
            SqliteRequestRepository._save_ext(conn, r)

        for n in seed["notifications"]:
            conn.execute("INSERT INTO notifications (id, user_id, message, created_at, is_read) VALUES (?, ?, ?, ?, ?)",
                         (to_int(n.id, "n"), to_int(n.user_id, "u"), n.message, ts(n.created_at), int(n.read)))
            write_notification_ext(conn, to_int(n.id, "n"), n)

        conn.executemany("INSERT INTO knowledge_base (question, answer, source) VALUES (?, ?, ?)",
                         [(x["question"], x["answer"], x["source"]) for x in qa])


def ensure_credentials(demo_password: str) -> None:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT u.id, u.email FROM users u LEFT JOIN api_user_credentials c "
                            "ON c.user_id = u.id WHERE c.user_id IS NULL").fetchall()
        for r in rows:
            if not r["email"]:
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (f"user{r['id']}@janamen.kz", r["id"]))
            conn.execute("INSERT INTO api_user_credentials (user_id, password_hash) VALUES (?, ?)",
                         (r["id"], _demo_hash(demo_password)))
    if rows:
        log.info("Созданы логины для %d сотрудник(ов) без пароля", len(rows))


def load_qa_rows() -> list:
    with db.get_connection() as conn:
        return conn.execute("SELECT id, question, answer, source FROM knowledge_base ORDER BY id").fetchall()
