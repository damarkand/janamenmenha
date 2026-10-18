"""Слой доступа к данным для Digital HR (SQLite).

Запуск напрямую создаёт базу и заполняет её тестовыми данными:
    python database.py

Путь к базе можно переопределить переменной окружения DIGITAL_HR_DB.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

DB_PATH = Path(
    os.environ.get("DIGITAL_HR_DB", Path(__file__).with_name("digital_hr.db"))
)

# В базе хранятся коды, а русские названия подставляются только при выводе.
REQUEST_TYPES = {
    "vacation": "Отпуск",
    "advance": "Аванс",
    "sick_leave": "Больничный",
    "other": "Другое",
}
REQUEST_STATUSES = {
    "pending": "В обработке",
    "approved": "Одобрена",
    "rejected": "Отклонена",
    "cancelled": "Отменена",
}
COURSE_STATUSES = {
    "assigned": "Назначен",
    "in_progress": "В процессе",
    "completed": "Завершён",
}
ROLES = ("worker", "manager", "hr")


# --------------------------------------------------------------------------
# Исключения
# --------------------------------------------------------------------------
class HRError(Exception):
    """Базовая ошибка бизнес-логики (текст можно показывать пользователю)."""


class NotFoundError(HRError):
    """Запись не найдена."""


class ValidationError(HRError):
    """Некорректные входные данные."""


class AccessDeniedError(HRError):
    """Нет прав на действие."""


# --------------------------------------------------------------------------
# Соединение и схема
# --------------------------------------------------------------------------
@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Открывает соединение, делает commit/rollback и ГАРАНТИРОВАННО закрывает его."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _in_list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY,
    full_name          TEXT NOT NULL,
    company            TEXT NOT NULL,
    position           TEXT NOT NULL,
    department         TEXT NOT NULL,
    manager_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    hire_date          TEXT,
    vacation_days_left INTEGER NOT NULL DEFAULT 0 CHECK (vacation_days_left >= 0),
    role               TEXT NOT NULL CHECK (role IN ({_in_list(ROLES)})),
    telegram_id        INTEGER UNIQUE,
    email              TEXT UNIQUE,
    password           TEXT NOT NULL DEFAULT 'Passw0rd!'
);

CREATE TABLE IF NOT EXISTS requests (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_type     TEXT NOT NULL CHECK (request_type IN ({_in_list(REQUEST_TYPES)})),
    details          TEXT NOT NULL DEFAULT '',
    start_date       TEXT,
    end_date         TEXT,
    days             INTEGER CHECK (days IS NULL OR days > 0),
    amount           REAL CHECK (amount IS NULL OR amount > 0),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ({_in_list(REQUEST_STATUSES)})),
    approver_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decision_comment TEXT,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at       TEXT,
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS courses (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL UNIQUE,
    description   TEXT,
    material_link TEXT
);

CREATE TABLE IF NOT EXISTS user_courses (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    progress  INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    status    TEXT NOT NULL DEFAULT 'assigned'
              CHECK (status IN ({_in_list(COURSE_STATUSES)})),
    UNIQUE (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_read    INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id       INTEGER PRIMARY KEY,
    question TEXT NOT NULL,
    answer   TEXT NOT NULL,
    source   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_manager        ON users(manager_id);
CREATE INDEX IF NOT EXISTS idx_requests_user        ON requests(user_id);
CREATE INDEX IF NOT EXISTS idx_requests_status      ON requests(status);
CREATE INDEX IF NOT EXISTS idx_notifications_user   ON notifications(user_id, is_read);
"""


def init_db() -> None:
    """Создаёт все таблицы и индексы. Ошибки НЕ глотаются."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("База данных инициализирована: %s", DB_PATH)


# --------------------------------------------------------------------------
# Тестовые данные
# --------------------------------------------------------------------------
def seed_test_data() -> bool:
    """Заполняет пустую базу демо-данными. Возвращает False, если данные уже есть.

    Id пользователей зафиксированы (1 — сотрудник, 2 — руководитель, 3 — HR),
    а вставка идёт в порядке «сначала руководитель», иначе FK на manager_id падает.
    """
    with get_connection() as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return False

        conn.executemany(
            """
            INSERT INTO users (id, full_name, company, position, department,
                               manager_id, hire_date, vacation_days_left, role, password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (2, "Тимур Сериков", "Jana Post", "Руководитель отдела",
                 "IT отдел", None, "2020-01-10", 24, "manager", "Passw0rd!"),
                (3, "Динара Нурлановна", "Jana Post", "HR-администратор",
                 "Департамент персонала", None, "2019-05-20", 30, "hr", "Passw0rd!"),
                (1, "Айгерим Смагулова", "Jana Post", "Младший специалист",
                 "IT отдел", 2, "2024-06-15", 18, "worker", "Passw0rd!"),
            ],
        )

        conn.executemany(
            "INSERT INTO courses (id, title, description, material_link) VALUES (?, ?, ?, ?)",
            [
                (1, "Основы информационной безопасности",
                 "Базовый курс по кибербезопасности.",
                 "https://jana.academy/infosec"),
                (2, "Этика и стандарты компании Jana Post",
                 "Вводный курс для новых сотрудников.",
                 "https://jana.academy/ethics"),
            ],
        )
        conn.execute(
            "INSERT INTO user_courses (user_id, course_id, progress, status) VALUES (1, 1, 50, 'in_progress')"
        )

        conn.executemany(
            "INSERT INTO knowledge_base (question, answer, source) VALUES (?, ?, ?)",
            [
                ("Как оформить отпуск?",
                 "Перейдите в раздел 'HR-сервис' -> 'Создать заявку', выберите "
                 "'Отпуск', укажите даты и отправьте руководителю.",
                 "Внутренний регламент HR №4 об отпусках"),
                ("Когда выплачивается аванс?",
                 "Аванс выплачивается 25-го числа каждого месяца, зарплата — 10-го.",
                 "Положение об оплате труда п. 2.1"),
                ("Сколько дней отпуска мне положено?",
                 "Ежегодный оплачиваемый отпуск — 24 календарных дня. "
                 "Остаток дней виден в вашем профиле.",
                 "Трудовой кодекс РК, ст. 88"),
                ("Что делать при болезни?",
                 "Сообщите руководителю в день заболевания и оформите больничный "
                 "лист; после выздоровления загрузите его в HR-сервис.",
                 "Внутренний регламент HR №7 о листках нетрудоспособности"),
            ],
        )
        conn.execute(
            "INSERT INTO notifications (user_id, message) VALUES (1, ?)",
            ("Добро пожаловать в Digital HR! Вам назначен курс по информационной безопасности.",),
        )
    logger.info("Тестовые данные загружены")
    return True


# --------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------
def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"{field}: ожидается дата в формате ГГГГ-ММ-ДД") from None


def _notify(conn: sqlite3.Connection, user_id: int, message: str) -> None:
    conn.execute(
        "INSERT INTO notifications (user_id, message) VALUES (?, ?)", (user_id, message)
    )


def _request_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["type_label"] = REQUEST_TYPES.get(data["request_type"], data["request_type"])
    data["status_label"] = REQUEST_STATUSES.get(data["status"], data["status"])
    return data


# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------
def get_user(user_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    return dict(row) if row else None


def link_telegram(user_id: int, telegram_id: int) -> None:
    """Привязывает Telegram-аккаунт к сотруднику."""
    with get_connection() as conn:
        try:
            cur = conn.execute(
                "UPDATE users SET telegram_id = ? WHERE id = ?", (telegram_id, user_id)
            )
        except sqlite3.IntegrityError:
            raise ValidationError("Этот Telegram-аккаунт уже привязан к другому сотруднику") from None
        if cur.rowcount == 0:
            raise NotFoundError(f"Сотрудник {user_id} не найден")


# --------------------------------------------------------------------------
# Курсы
# --------------------------------------------------------------------------
def get_user_courses(user_id: int) -> list[dict]:
    """Курсы пользователя и прогресс по ним."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id AS course_id, c.title, c.description, c.material_link,
                   uc.progress, uc.status
            FROM user_courses uc
            JOIN courses c ON uc.course_id = c.id
            WHERE uc.user_id = ?
            ORDER BY c.title
            """,
            (user_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["status_label"] = COURSE_STATUSES.get(item["status"], item["status"])
        result.append(item)
    return result


def assign_course(user_id: int, course_id: int) -> bool:
    """Назначает курс. False — если курс уже был назначен."""
    with get_connection() as conn:
        course = conn.execute("SELECT title FROM courses WHERE id = ?", (course_id,)).fetchone()
        if course is None:
            raise NotFoundError(f"Курс {course_id} не найден")
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise NotFoundError(f"Сотрудник {user_id} не найден")
        cur = conn.execute(
            "INSERT OR IGNORE INTO user_courses (user_id, course_id) VALUES (?, ?)",
            (user_id, course_id),
        )
        if cur.rowcount == 0:
            return False
        _notify(conn, user_id, f"Вам назначен курс «{course['title']}»")
        return True


def update_course_progress(user_id: int, course_id: int, progress: int) -> dict:
    """Обновляет прогресс (0–100); статус выставляется автоматически."""
    if not isinstance(progress, int) or isinstance(progress, bool) or not 0 <= progress <= 100:
        raise ValidationError("Прогресс должен быть целым числом от 0 до 100")
    status = "completed" if progress == 100 else "in_progress" if progress > 0 else "assigned"
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE user_courses SET progress = ?, status = ? WHERE user_id = ? AND course_id = ?",
            (progress, status, user_id, course_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError("Этот курс не назначен сотруднику")
        if status == "completed":
            title = conn.execute("SELECT title FROM courses WHERE id = ?", (course_id,)).fetchone()["title"]
            _notify(conn, user_id, f"Поздравляем! Вы завершили курс «{title}»")
    return {"progress": progress, "status": status, "status_label": COURSE_STATUSES[status]}


# --------------------------------------------------------------------------
# Заявки
# --------------------------------------------------------------------------
def create_request(
    user_id: int,
    request_type: str,
    details: str = "",
    start_date: Any = None,
    end_date: Any = None,
    amount: float | None = None,
) -> int:
    """Создаёт заявку и уведомляет руководителя (или HR, если руководителя нет).

    Для отпуска нужны start_date/end_date (календарные дни, включительно);
    для аванса — amount. Возвращает id заявки.
    """
    if request_type not in REQUEST_TYPES:
        raise ValidationError(f"Неизвестный тип заявки: {request_type!r}")

    with get_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise NotFoundError(f"Сотрудник {user_id} не найден")

        start = end = days = None
        if request_type == "vacation":
            if start_date is None or end_date is None:
                raise ValidationError("Для отпуска укажите даты начала и окончания")
            start = _parse_date(start_date, "Дата начала")
            end = _parse_date(end_date, "Дата окончания")
            if end < start:
                raise ValidationError("Дата окончания раньше даты начала")
            days = (end - start).days + 1
            if days > user["vacation_days_left"]:
                raise ValidationError(
                    f"Недостаточно дней отпуска: нужно {days}, осталось {user['vacation_days_left']}"
                )
            overlap = conn.execute(
                """
                SELECT 1 FROM requests
                WHERE user_id = ? AND request_type = 'vacation'
                  AND status IN ('pending', 'approved')
                  AND start_date <= ? AND end_date >= ?
                """,
                (user_id, end.isoformat(), start.isoformat()),
            ).fetchone()
            if overlap:
                raise ValidationError("Даты пересекаются с другой заявкой на отпуск")
        elif request_type == "advance":
            if amount is None or amount <= 0:
                raise ValidationError("Для аванса укажите сумму больше нуля")

        cur = conn.execute(
            """
            INSERT INTO requests (user_id, request_type, details, start_date, end_date, days, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, request_type, details.strip(),
             start.isoformat() if start else None,
             end.isoformat() if end else None, days, amount),
        )
        request_id = cur.lastrowid

        if user["manager_id"]:
            recipients = [user["manager_id"]]
        else:
            recipients = [r["id"] for r in conn.execute(
                "SELECT id FROM users WHERE role = 'hr' AND id != ?", (user_id,))]
        text = f"Новая заявка №{request_id} от {user['full_name']}: {REQUEST_TYPES[request_type]}"
        if start:
            text += f" ({start.isoformat()} — {end.isoformat()}, {days} дн.)"
        for rid in recipients:
            _notify(conn, rid, text)
    return request_id


def get_user_requests(user_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM requests WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [_request_to_dict(r) for r in rows]


def get_requests_to_approve(approver_id: int) -> list[dict]:
    """Заявки на согласовании: у руководителя — его подчинённых, у HR — все."""
    with get_connection() as conn:
        approver = conn.execute("SELECT role FROM users WHERE id = ?", (approver_id,)).fetchone()
        if approver is None:
            raise NotFoundError(f"Сотрудник {approver_id} не найден")
        rows = conn.execute(
            """
            SELECT r.*, u.full_name AS employee_name
            FROM requests r JOIN users u ON u.id = r.user_id
            WHERE r.status = 'pending' AND r.user_id != ?
              AND (? = 'hr' OR u.manager_id = ?)
            ORDER BY r.created_at, r.id
            """,
            (approver_id, approver["role"], approver_id),
        ).fetchall()
    return [_request_to_dict(r) for r in rows]


def decide_request(request_id: int, approver_id: int, approve: bool, comment: str = "") -> dict:
    """Одобряет/отклоняет заявку. Всё выполняется в одной транзакции:
    при ошибке списания дней статус заявки тоже откатывается."""
    with get_connection() as conn:
        req = conn.execute(
            """
            SELECT r.*, u.manager_id FROM requests r
            JOIN users u ON u.id = r.user_id WHERE r.id = ?
            """,
            (request_id,),
        ).fetchone()
        if req is None:
            raise NotFoundError(f"Заявка {request_id} не найдена")
        approver = conn.execute("SELECT role FROM users WHERE id = ?", (approver_id,)).fetchone()
        if approver is None:
            raise NotFoundError(f"Сотрудник {approver_id} не найден")
        if approver_id == req["user_id"]:
            raise AccessDeniedError("Нельзя согласовывать собственную заявку")
        if approver["role"] != "hr" and req["manager_id"] != approver_id:
            raise AccessDeniedError("Вы не можете согласовывать эту заявку")

        new_status = "approved" if approve else "rejected"
        cur = conn.execute(
            """
            UPDATE requests
            SET status = ?, approver_id = ?, decision_comment = ?, decided_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
            """,
            (new_status, approver_id, comment.strip() or None, request_id),
        )
        if cur.rowcount == 0:
            raise HRError("Заявка уже обработана")

        if approve and req["request_type"] == "vacation":
            cur = conn.execute(
                """
                UPDATE users SET vacation_days_left = vacation_days_left - ?
                WHERE id = ? AND vacation_days_left >= ?
                """,
                (req["days"], req["user_id"], req["days"]),
            )
            if cur.rowcount == 0:
                raise HRError("У сотрудника не хватает дней отпуска")

        verdict = "одобрена" if approve else "отклонена"
        msg = f"Ваша заявка №{request_id} ({REQUEST_TYPES[req['request_type']]}) {verdict}"
        if comment.strip():
            msg += f". Комментарий: {comment.strip()}"
        _notify(conn, req["user_id"], msg)

        updated = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    return _request_to_dict(updated)


def cancel_request(request_id: int, user_id: int) -> None:
    """Сотрудник отменяет свою заявку, пока она не обработана."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE requests SET status = 'cancelled', decided_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ? AND status = 'pending'",
            (request_id, user_id),
        )
        if cur.rowcount == 0:
            raise HRError("Заявка не найдена или уже обработана")


# --------------------------------------------------------------------------
# Уведомления
# --------------------------------------------------------------------------
def get_notifications(user_id: int, unread_only: bool = True, limit: int = 20) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    if unread_only:
        sql += " AND is_read = 0"
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, (user_id, limit))]


def mark_notifications_read(user_id: int) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user_id,)
        )
        return cur.rowcount


# --------------------------------------------------------------------------
# База знаний для AI-ассистента
# --------------------------------------------------------------------------
_STOP_WORDS = {
    "как", "что", "где", "когда", "мне", "нужно", "можно", "для", "или", "это",
    "при", "есть", "мой", "моя", "мои", "какой", "какие", "сколько", "хочу",
    "чтобы", "если", "там", "тут", "надо", "еще", "она", "они", "его", "нас", "вас",
}


def _stems(text: str) -> set[str]:
    """Грубая нормализация: нижний регистр, ё→е, первые 5 букв слова.
    Так «отпуск», «отпуске», «ОТПУСКА» дают одну основу."""
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    return {w[:5] for w in words if len(w) >= 3 and w not in _STOP_WORDS}


def search_ai_knowledge(query: str, limit: int = 3) -> list[dict]:
    """Ищет по вопросам и ответам, работает с целой фразой и разными формами слов.
    Результаты отсортированы по релевантности."""
    query_stems = _stems(query)
    if not query_stems:
        return []
    with get_connection() as conn:
        rows = conn.execute("SELECT question, answer, source FROM knowledge_base").fetchall()
    scored = []
    for row in rows:
        q_stems = _stems(row["question"])
        a_stems = _stems(row["answer"])
        score = 2 * len(query_stems & q_stems) + len(query_stems & (a_stems - q_stems))
        if score > 0:
            scored.append({**dict(row), "score": score})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    seed_test_data()
