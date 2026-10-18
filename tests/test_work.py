from datetime import date, timedelta

import pytest

from app.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.domain import NotificationType, RequestStatus, RequestType, TaskPriority, TaskStatus
from app.models.schemas import VacationCreate
from app.services.work_service import hours_per_day
from tests.conftest import TODAY


def U(c, uid):
    return c.users.get(uid)


# Задачи
def test_demo_tasks_are_relative_to_today(container):
    tasks = container.tasks.list(U(container, "u-3"))
    assert len(tasks) == 6
    assert [t.status for t in tasks][:2] == [TaskStatus.IN_PROGRESS, TaskStatus.IN_PROGRESS]
    review = next(t for t in tasks if t.title.startswith("Код-ревью"))
    assert review.due_date == TODAY + timedelta(days=1)


def test_create_own_task_and_validation(container):
    emp = U(container, "u-3")
    t = container.tasks.create(emp, "  Позвонить в банк  ", category="", priority="high", due_date=TODAY)
    assert t.title == "Позвонить в банк" and t.category == "Общее" and t.priority == TaskPriority.HIGH
    assert t.user_id == emp.id and t.created_by == emp.id
    with pytest.raises(BusinessRuleError):
        container.tasks.create(emp, "   ")


def test_manager_assigns_task_to_team_only(container):
    mgr, emp = U(container, "u-2"), U(container, "u-3")
    t = container.tasks.create(mgr, "Подготовить демо", user_id="u-3", due_date=TODAY + timedelta(days=2))
    note = container.notifications.list_for(emp)[0]
    assert note.type == NotificationType.TASK_ASSIGNED and "Подготовить демо" in note.message
    with pytest.raises(ForbiddenError):
        container.tasks.create(mgr, "Чужому", user_id="u-6")
    with pytest.raises(ForbiddenError):
        container.tasks.create(emp, "Коллеге", user_id="u-4")
    assert container.tasks.get(mgr, t.id).user_id == "u-3"


def test_hr_assigns_anyone(container):
    assert container.tasks.create(U(container, "u-1"), "Анкета", user_id="u-6").user_id == "u-6"


def test_status_flow_and_completion_notice(container):
    mgr, emp = U(container, "u-2"), U(container, "u-3")
    t = container.tasks.create(mgr, "Сверка", user_id="u-3")
    container.tasks.set_status(emp, t.id, "in_progress")
    done = container.tasks.set_status(emp, t.id, TaskStatus.DONE)
    assert done.completed_at is not None
    assert container.notifications.list_for(mgr)[0].type == NotificationType.TASK_COMPLETED
    assert container.tasks.set_status(emp, t.id, "todo").completed_at is None


def test_task_visibility(container):
    t = container.tasks.list(U(container, "u-3"))[0]
    with pytest.raises(NotFoundError):
        container.tasks.get(U(container, "u-4"), t.id)
    with pytest.raises(NotFoundError):
        container.tasks.get(U(container, "u-5"), t.id)
    assert container.tasks.get(U(container, "u-2"), t.id).id == t.id
    assert container.tasks.get(U(container, "u-1"), t.id).id == t.id


def test_update_and_delete_rules(container):
    mgr, emp, other = U(container, "u-2"), U(container, "u-3"), U(container, "u-4")
    t = container.tasks.create(mgr, "Отчёт", user_id="u-3")
    updated = container.tasks.update(emp, t.id, title="Отчёт за октябрь", priority="low", description=None)
    assert updated.title == "Отчёт за октябрь" and updated.priority == TaskPriority.LOW
    with pytest.raises(BusinessRuleError):
        container.tasks.update(emp, t.id, title="  ")
    with pytest.raises(ForbiddenError):
        container.tasks.delete(emp, t.id)
    container.tasks.delete(mgr, t.id)
    with pytest.raises(NotFoundError):
        container.tasks.get(mgr, t.id)
    own = container.tasks.create(other, "Своя")
    container.tasks.delete(other, own.id)


def test_team_scope(container):
    mgr = U(container, "u-2")
    assert {t.user_id for t in container.tasks.list(mgr, "team")} == {"u-3", "u-4"}
    assert {t.user_id for t in container.tasks.list(mgr, "team", user_id="u-4")} == {"u-4"}
    with pytest.raises(ForbiddenError):
        container.tasks.list(mgr, "team", user_id="u-6")
    with pytest.raises(ForbiddenError):
        container.tasks.list(U(container, "u-3"), "team")
    with pytest.raises(BusinessRuleError):
        container.tasks.list(mgr, "all")
    assert all(t.status == TaskStatus.DONE for t in container.tasks.list(mgr, "team", status=TaskStatus.DONE))


# Учёт времени
def test_log_time_rules(container):
    emp = U(container, "u-3")
    e = container.time.log(emp, TODAY, 3.5, note=" Встречи ")
    assert e.hours == 3.5 and e.note == "Встречи"
    assert any(x.id == e.id for x in container.time.list(emp, TODAY, TODAY))
    with pytest.raises(BusinessRuleError):
        container.time.log(emp, TODAY + timedelta(days=1), 1)
    with pytest.raises(BusinessRuleError):
        container.time.log(emp, TODAY - timedelta(days=61), 1)
    with pytest.raises(BusinessRuleError):
        container.time.log(emp, TODAY, 0)
    with pytest.raises(BusinessRuleError):
        container.time.log(emp, TODAY, 21)
    with pytest.raises(BusinessRuleError):
        container.time.list(emp, TODAY, TODAY - timedelta(days=1))


def test_log_time_with_task(container):
    emp = U(container, "u-3")
    own = container.tasks.list(emp)[0]
    assert container.time.log(emp, TODAY, 1, task_id=own.id).task_id == own.id
    foreign = container.tasks.list(U(container, "u-4"))[0]
    with pytest.raises(BusinessRuleError):
        container.time.log(emp, TODAY, 1, task_id=foreign.id)


def test_delete_time_only_own(container):
    e = container.time.log(U(container, "u-3"), TODAY, 1)
    with pytest.raises(NotFoundError):
        container.time.delete(U(container, "u-4"), e.id)
    container.time.delete(U(container, "u-3"), e.id)
    assert all(x.id != e.id for x in container.time.list(U(container, "u-3"), TODAY, TODAY))


# График
def test_hours_per_day():
    from app.models.domain import WorkSchedule
    assert hours_per_day(WorkSchedule(id="u-1")) == 8
    assert hours_per_day(WorkSchedule(id="u-1", start_time="09:00", end_time="13:00", lunch_minutes=0)) == 4


def test_calendar_month(container):
    cal = container.schedules.calendar(U(container, "u-3"), "2026-10")
    days = {d["date"]: d for d in cal["days"]}
    assert len(days) == 31 and cal["hours_per_day"] == 8
    assert days[date(2026, 10, 25)]["type"] == "holiday" and days[date(2026, 10, 25)]["holiday"] == "День Республики"
    assert days[date(2026, 10, 24)]["type"] == "weekend" and days[date(2026, 10, 24)]["planned_hours"] == 0
    assert days[date(2026, 10, 19)]["type"] == "workday" and days[date(2026, 10, 19)]["planned_hours"] == 8
    assert days[TODAY]["is_today"]
    assert any(d["tasks_due"] for d in cal["days"])
    assert cal["summary"]["workdays"] == 22 and cal["summary"]["logged_hours"] > 0


def test_calendar_shows_vacations(container):
    emp = U(container, "u-3")
    req = container.requests.create_vacation(emp, VacationCreate(start_date=date(2026, 11, 2), end_date=date(2026, 11, 6)))
    cal = container.schedules.calendar(emp, "2026-11")
    assert cal["days"][1]["type"] == "vacation_pending"
    container.requests.approve(U(container, "u-2"), req.id)
    cal = container.schedules.calendar(emp, "2026-11")
    assert [d["type"] for d in cal["days"][1:6]] == ["vacation"] * 5 and cal["summary"]["vacation_days"] == 5


def test_calendar_access_and_format(container):
    with pytest.raises(ForbiddenError):
        container.schedules.calendar(U(container, "u-3"), "2026-10", "u-4")
    assert container.schedules.calendar(U(container, "u-2"), "2026-10", "u-4")["user_id"] == "u-4"
    with pytest.raises(BusinessRuleError):
        container.schedules.calendar(U(container, "u-3"), "октябрь")


def test_schedule_update_only_hr(container):
    hr, emp = U(container, "u-1"), U(container, "u-3")
    assert container.schedules.get(emp).work_format == "hybrid"
    with pytest.raises(ForbiddenError):
        container.schedules.update(emp, "u-3", start_time="08:00")
    s = container.schedules.update(hr, "u-3", work_days=[4, 0, 1, 1], start_time="08:00", end_time="12:00",
                                   lunch_minutes=0)
    assert s.work_days == [0, 1, 4] and hours_per_day(s) == 4
    assert container.schedules.get(emp).start_time == "08:00"
    with pytest.raises(BusinessRuleError):
        container.schedules.update(hr, "u-3", work_days=[9])
    with pytest.raises(BusinessRuleError):
        container.schedules.update(hr, "u-3", start_time="18:00", end_time="09:00")


# Дашборд
def test_my_dashboard(container):
    d = container.dashboard.me(U(container, "u-3"))
    c = d["cards"]
    assert c["open_tasks"] == 3 and c["vacation_days_left"] == 21 and c["courses_total"] == 2
    assert c["planned_week"] == 40 and 0 < c["hours_week"] <= 60
    assert len(d["charts"]["hours_by_day"]) == 14 and len(d["charts"]["tasks_done_by_week"]) == 8
    assert sum(w["count"] for w in d["charts"]["tasks_done_by_week"]) >= 2
    assert d["charts"]["tasks_by_status"] == {"todo": 1, "in_progress": 2, "done": 3}
    assert d["next_holiday"]["name"] == "День Республики"
    assert d["upcoming_tasks"] and all(t.status != TaskStatus.DONE for t in d["upcoming_tasks"])


def test_dashboard_overdue(container):
    emp = U(container, "u-3")
    container.tasks.create(emp, "Старое", due_date=TODAY - timedelta(days=2))
    assert container.dashboard.me(emp)["cards"]["overdue_tasks"] == 1


def test_team_dashboard(container):
    t = container.dashboard.team(U(container, "u-2"))
    assert [m["user"]["id"] for m in t["members"]] == ["u-4", "u-3"]
    assert t["totals"]["members"] == 2 and t["totals"]["pending_requests"] == 1
    assert container.dashboard.team(U(container, "u-1"))["totals"]["members"] == 5
    with pytest.raises(ForbiddenError):
        container.dashboard.team(U(container, "u-3"))


# Справки
def test_certificate_request_goes_to_hr(container):
    emp, hr = U(container, "u-3"), U(container, "u-1")
    req = container.requests.create_certificate(emp, "employment", "для банка")
    assert req.type == RequestType.OTHER and req.status == RequestStatus.PENDING
    assert req.comment == "Справка с места работы. для банка"
    assert any("Справка с места работы" in n.message for n in container.notifications.list_for(hr))
    assert container.requests.approve(hr, req.id).status == RequestStatus.APPROVED
    with pytest.raises(BusinessRuleError):
        container.requests.create_certificate(emp, "passport")
