from datetime import timedelta

import pytest

import database as db
from app.container import Container
from app.core.config import Settings
from app.models.domain import EnrollmentStatus, NotificationType, RequestStatus, RequestType, Role
from app.models.schemas import AdvanceCreate, VacationCreate
from app.repositories.sqlite import parse_ts, to_id, to_int, ts
from tests.conftest import TODAY


@pytest.fixture
def sqlite_settings(tmp_path) -> Settings:
    s = Settings()
    s.storage, s.db_path, s.integration_mode = "sqlite", tmp_path / "hr.db", "mock"
    s.ai_mode = "off"
    return s


@pytest.fixture
def c(sqlite_settings) -> Container:
    return Container(sqlite_settings, today=lambda: TODAY)


def U(c, uid):
    return c.users.get(uid)


# Преобразования
def test_id_and_timestamp_mapping():
    assert to_int("u-3", "u") == 3 and to_int("3", "u") == 3
    assert to_int("req-3", "u") is None and to_int("u-abc", "u") is None and to_int(None, "u") is None
    assert to_id(7, "req") == "req-7" and to_id(None, "req") is None
    stamp = "2026-06-02 08:15:00"
    assert ts(parse_ts(stamp)).startswith(stamp)
    assert parse_ts("2026-06-02T08:15:00Z") == parse_ts(stamp)


def test_unknown_storage_rejected(sqlite_settings):
    sqlite_settings.storage = "mongo"
    with pytest.raises(ValueError):
        Container(sqlite_settings)


# Схема и демо-данные
def test_empty_database_is_seeded_and_api_tables_added(c):
    with db.get_connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("users", "requests", "courses", "user_courses", "notifications", "knowledge_base")}
    assert {"users", "requests", "courses", "user_courses", "notifications", "knowledge_base"} <= tables
    assert {"api_user_credentials", "api_request_history", "api_escalations"} <= tables
    assert counts == {"users": 6, "requests": 3, "courses": 4, "user_courses": 4, "notifications": 4,
                      "knowledge_base": 4}
    assert db.get_user(3)["role"] == "worker" and db.get_user(3)["manager_id"] == 2


def test_data_survives_restart(sqlite_settings, c):
    req = c.requests.create_advance(U(c, "u-3"), AdvanceCreate(amount=1000))
    again = Container(sqlite_settings, today=lambda: TODAY)
    assert again.request_repo.get(req.id).advance.amount == 1000
    assert len(again.users.list()) == 6


def test_database_seeded_by_database_py_gets_logins(tmp_path):
    s = Settings()
    s.storage, s.db_path, s.integration_mode = "sqlite", tmp_path / "bot.db", "mock"
    s.ai_mode = "off"
    db.DB_PATH = s.db_path
    db.init_db()
    assert db.seed_test_data()

    c = Container(s, today=lambda: TODAY)
    user, _, _ = c.auth.login("user1@janamen.kz", s.demo_password)
    assert user.full_name == "Айгерим Смагулова" and user.role == Role.EMPLOYEE and user.manager_id == "u-2"
    assert c.users.get("u-3").role == Role.HR
    assert user.salary == s.default_salary
    assert db.get_user(1)["email"] == "user1@janamen.kz"
    assert c.lms.my_enrollments(user)[0].status == EnrollmentStatus.IN_PROGRESS
    out = c.assistant.ask("Когда выплачивается аванс?")
    assert out.found and out.sources[0].document == "Положение об оплате труда п. 2.1"


# API → бот
def test_request_created_in_api_visible_to_bot(c):
    req = c.requests.create_vacation(U(c, "u-3"), VacationCreate(
        start_date=TODAY + timedelta(days=20), end_date=TODAY + timedelta(days=24), comment="Семья"))
    bot_view = db.get_user_requests(3)[0]
    assert bot_view["id"] == to_int(req.id, "req") and bot_view["status_label"] == "В обработке"
    assert bot_view["days"] == 5 and bot_view["details"] == "Семья"
    assert [r["id"] for r in db.get_requests_to_approve(2)] == [2, bot_view["id"]]

    c.requests.approve(U(c, "u-2"), req.id, "Хорошего отдыха")
    bot_view = db.get_user_requests(3)[0]
    assert bot_view["status"] == "approved" and bot_view["approver_id"] == 2
    assert bot_view["decision_comment"] == "Хорошего отдыха" and bot_view["decided_at"]
    assert db.get_user(3)["vacation_days_left"] == 16
    with db.get_connection() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM api_request_history WHERE request_id = ? ORDER BY id", (bot_view["id"],))]
        refs = {r["key"] for r in conn.execute(
            "SELECT key FROM api_request_refs WHERE request_id = ?", (bot_view["id"],))}
    assert actions == ["created", "approved"] and refs == {"zup_doc_id", "documentolog_doc_id"}


def test_api_notifications_visible_to_bot(c):
    c.requests.create_advance(U(c, "u-3"), AdvanceCreate(amount=5000))
    texts = [n["message"] for n in db.get_notifications(2)]
    assert any("Данияр Касымов подал(а) заявку" in t for t in texts)
    assert db.mark_notifications_read(2) >= 1
    assert c.notifications.unread_count("u-2") == 0


def test_course_progress_from_api_visible_to_bot(c):
    c.lms.submit_test(U(c, "u-3"), "c-2", [2, 0, 1, 1, 1])
    course = next(x for x in db.get_user_courses(3) if x["course_id"] == 2)
    assert course["status"] == "completed" and course["progress"] == 100


# Бот → API
def test_bot_vacation_request_approved_through_api(c):
    rid = db.create_request(3, "vacation", "через бота", (TODAY + timedelta(days=40)).isoformat(),
                            (TODAY + timedelta(days=41)).isoformat())
    req = c.requests.get(U(c, "u-2"), to_id(rid, "req"))
    assert req.vacation.days == 2 and req.vacation.comment == "через бота"
    assert [h.action for h in req.history] == ["created"]

    approved = c.requests.approve(U(c, "u-2"), req.id, None)
    assert approved.status == RequestStatus.APPROVED
    assert [h.action for h in c.requests.get(U(c, "u-3"), req.id).history] == ["created", "approved"]
    assert db.get_user(3)["vacation_days_left"] == 19


def test_bot_sick_leave_and_decided_request(c):
    rid = db.create_request(3, "sick_leave", "ОРВИ, лист открыт")
    sick = c.requests.get(U(c, "u-3"), to_id(rid, "req"))
    assert sick.type == RequestType.SICK_LEAVE and sick.comment == "ОРВИ, лист открыт"
    approved = c.requests.approve(U(c, "u-2"), sick.id, "Выздоравливайте")
    assert approved.status == RequestStatus.APPROVED and "documentolog_doc_id" not in approved.external_refs

    rid2 = db.create_request(3, "other", "Справка с места работы")
    db.decide_request(rid2, 2, False, "Обратитесь в HR")
    other = c.requests.get(U(c, "u-3"), to_id(rid2, "req"))
    assert other.status == RequestStatus.REJECTED and other.decided_by == "u-2"
    assert other.history[-1].comment == "Обратитесь в HR"


def test_bot_course_assignment_and_progress(c):
    assert db.assign_course(4, 3)
    e = c.enrollment_repo.find("u-4", "c-3")
    assert e.status == EnrollmentStatus.NOT_STARTED and e.assigned_at is None
    db.update_course_progress(4, 3, 60)
    assert c.enrollment_repo.find("u-4", "c-3").progress == 60
    notes = c.notifications.list_for(U(c, "u-4"))
    assert notes[0].type == NotificationType.GENERAL and "Эффективная обратная связь" in notes[0].message


def test_bot_telegram_link_does_not_break_api(c):
    db.link_telegram(3, 123456789)
    assert db.get_user_by_telegram_id(123456789)["id"] == 3
    assert c.auth.login("employee@janamen.kz", "Passw0rd!")[0].id == "u-3"


def test_knowledge_base_rows_added_by_bot_are_used_immediately(c):
    with db.get_connection() as conn:
        conn.execute("INSERT INTO knowledge_base (question, answer, source) VALUES (?, ?, ?)",
                     ("Есть ли в офисе парковка?", "Парковка для сотрудников бесплатная, въезд с ул. Абая.",
                      "Памятка для сотрудников"))
    out = c.assistant.ask("Где парковка для сотрудников?")
    assert out.found and out.sources[0].document == "Памятка для сотрудников"
    assert out.sources[0].file.startswith("knowledge_base#")


def test_tasks_and_time_persist_across_restart(sqlite_settings, c):
    t = c.tasks.create(U(c, "u-3"), "Сохраниться в базе")
    e = c.time.log(U(c, "u-3"), TODAY, 2)
    again = Container(sqlite_settings, today=lambda: TODAY)
    assert again.tasks.get(again.users.get("u-3"), t.id).title == "Сохраниться в базе"
    assert any(x.id == e.id for x in again.time.list(again.users.get("u-3"), TODAY, TODAY))
    assert len(again.tasks.list(again.users.get("u-3"))) == 7


def test_work_data_added_to_existing_database(tmp_path):
    s = Settings()
    s.storage, s.db_path, s.integration_mode, s.ai_mode = "sqlite", tmp_path / "old.db", "mock", "off"
    db.DB_PATH = s.db_path
    db.init_db()
    db.seed_test_data()
    c = Container(s, today=lambda: TODAY)
    owners = {t.user_id for t in c.task_repo.for_users({"u-1", "u-2", "u-3"})}
    assert owners and owners <= {"u-1", "u-2", "u-3"}
    assert c.dashboard.me(c.users.get("u-1"))["cards"]["hours_week"] > 0
    with db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM api_user_schedule").fetchone()[0] == 3
