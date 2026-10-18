from datetime import date, timedelta

import pytest

from app.container import Container
from app.core.config import Settings
from app.core.errors import AuthError, BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.models.domain import EnrollmentStatus, NotificationType, RequestStatus
from app.models.schemas import AdvanceCreate, VacationCreate

TODAY = date(2026, 10, 17)


@pytest.fixture
def c(container):
    return container


def U(c, email):
    return c.users.get_by_email(email)


# Авторизация
def test_login_ok_and_bad_password(c):
    user, token, _ = c.auth.login("employee@janamen.kz", "Passw0rd!")
    assert c.auth.resolve_token(token).id == user.id
    with pytest.raises(AuthError):
        c.auth.login("employee@janamen.kz", "wrong")


# Профили и права доступа
def test_employee_sees_only_own_profile(c):
    emp = U(c, "employee@janamen.kz")
    p = c.profiles.get_profile(emp, emp.id)
    assert p.read_only and p.advance_limit == 300000 and p.manager.full_name == "Ерлан Тулеуов"
    with pytest.raises(ForbiddenError):
        c.profiles.get_profile(emp, "u-4")
    with pytest.raises(ForbiddenError):
        c.profiles.list_visible_users(emp)


def test_manager_sees_only_direct_reports(c):
    mgr = U(c, "manager@janamen.kz")
    assert {m.id for m in c.profiles.list_visible_users(mgr)} == {"u-3", "u-4"}
    assert c.profiles.get_profile(mgr, "u-3").advance_limit is None
    with pytest.raises(ForbiddenError):
        c.profiles.get_profile(mgr, "u-6")


def test_hr_sees_everyone(c):
    hr = U(c, "hr@janamen.kz")
    assert len(c.profiles.list_visible_users(hr)) == 5
    assert c.profiles.get_profile(hr, "u-6").advance_limit == 210000


# Заявки
def test_vacation_full_flow(c):
    emp, mgr = U(c, "employee@janamen.kz"), U(c, "manager@janamen.kz")
    req = c.requests.create_vacation(emp, VacationCreate(start_date=TODAY + timedelta(days=20),
                                                         end_date=TODAY + timedelta(days=29)))
    assert req.status == RequestStatus.PENDING and req.vacation.days == 10
    assert any(n.type == NotificationType.REQUEST_CREATED for n in c.notifications.list_for(mgr))

    with pytest.raises(ForbiddenError):
        c.requests.approve(emp, req.id)
    with pytest.raises(NotFoundError):
        c.requests.approve(U(c, "manager2@janamen.kz"), req.id)

    req = c.requests.approve(mgr, req.id, "ok")
    assert req.status == RequestStatus.APPROVED and req.decided_by == mgr.id
    assert req.external_refs["documentolog_doc_id"].startswith("DL-")
    assert U(c, "employee@janamen.kz").vacation_days_left == 11
    assert [h.action for h in req.history] == ["created", "approved"]
    assert any(n.type == NotificationType.REQUEST_STATUS_CHANGED for n in c.notifications.list_for(emp))
    with pytest.raises(ConflictError):
        c.requests.reject(mgr, req.id, "late")


def test_vacation_validation(c):
    emp = U(c, "employee2@janamen.kz")
    with pytest.raises(BusinessRuleError):
        c.requests.create_vacation(emp, VacationCreate(start_date=TODAY - timedelta(days=1), end_date=TODAY))
    with pytest.raises(BusinessRuleError):
        c.requests.create_vacation(emp, VacationCreate(start_date=TODAY + timedelta(days=5),
                                                       end_date=TODAY + timedelta(days=30)))
    c.requests.create_vacation(emp, VacationCreate(start_date=TODAY + timedelta(days=5),
                                                   end_date=TODAY + timedelta(days=12)))
    with pytest.raises(ConflictError):
        c.requests.create_vacation(emp, VacationCreate(start_date=TODAY + timedelta(days=10),
                                                       end_date=TODAY + timedelta(days=11)))
    with pytest.raises(BusinessRuleError):
        c.requests.create_vacation(emp, VacationCreate(start_date=TODAY + timedelta(days=40),
                                                       end_date=TODAY + timedelta(days=44)))


def test_advance_rules_and_reject(c):
    emp, mgr = U(c, "employee@janamen.kz"), U(c, "manager@janamen.kz")
    with pytest.raises(BusinessRuleError):
        c.requests.create_advance(emp, AdvanceCreate(amount=300001))
    req = c.requests.create_advance(emp, AdvanceCreate(amount=100000))
    with pytest.raises(ConflictError):
        c.requests.create_advance(emp, AdvanceCreate(amount=1000))
    with pytest.raises(BusinessRuleError):
        c.requests.reject(mgr, req.id, "")
    assert c.requests.reject(mgr, req.id, "Бюджет").status == RequestStatus.REJECTED


def test_manager_request_goes_to_hr(c):
    mgr, hr = U(c, "manager@janamen.kz"), U(c, "hr@janamen.kz")
    req = c.requests.create_advance(mgr, AdvanceCreate(amount=10000))
    assert [a.id for a in c.requests.approvers_for(mgr)] == [hr.id]
    assert c.requests.approve(hr, req.id).status == RequestStatus.APPROVED


def test_request_scopes(c):
    emp, mgr, hr = U(c, "employee@janamen.kz"), U(c, "manager@janamen.kz"), U(c, "hr@janamen.kz")
    assert {r.id for r in c.requests.list(mgr, "team")} == {"req-1", "req-2"}
    assert len(c.requests.list(hr, "all")) == 3
    with pytest.raises(ForbiddenError):
        c.requests.list(emp, "team")
    with pytest.raises(ForbiddenError):
        c.requests.list(mgr, "all")
    with pytest.raises(NotFoundError):
        c.requests.get(emp, "req-2")


def test_cancel_only_own_pending(c):
    emp2, mgr = U(c, "employee2@janamen.kz"), U(c, "manager@janamen.kz")
    with pytest.raises(ForbiddenError):
        c.requests.cancel(mgr, "req-2")
    assert c.requests.cancel(emp2, "req-2").status == RequestStatus.CANCELLED


# Обучение
def test_assign_and_complete_course(c):
    mgr, emp = U(c, "manager@janamen.kz"), U(c, "employee2@janamen.kz")
    c.lms.assign(mgr, emp.id, "c-3")
    with pytest.raises(ForbiddenError):
        c.lms.assign(mgr, "u-6", "c-3")
    with pytest.raises(ForbiddenError):
        c.lms.assign(emp, "u-3", "c-3")
    c.lms.start(emp, "c-3")
    e = c.lms.update_progress(emp, "c-3", 100)
    assert e.progress == 99 and e.status == EnrollmentStatus.IN_PROGRESS
    r = c.lms.submit_test(emp, "c-3", [1, 1])
    assert not r.passed and r.score == 50
    r = c.lms.submit_test(emp, "c-3", [0, 1])
    assert r.passed and r.status == EnrollmentStatus.COMPLETED and r.attempts == 2
    assert any(n.type == NotificationType.COURSE_COMPLETED for n in c.notifications.list_for(mgr))


def test_course_without_test_and_team_progress(c):
    emp, mgr = U(c, "employee@janamen.kz"), U(c, "manager@janamen.kz")
    c.lms.enroll_self(emp, "c-4")
    assert c.lms.update_progress(emp, "c-4", 100).status == EnrollmentStatus.COMPLETED
    assert {e.user_id for e in c.lms.team_progress(mgr)} <= {"u-3", "u-4"}
    with pytest.raises(ForbiddenError):
        c.lms.team_progress(mgr, "u-6")


# Уведомления
def test_notifications_isolated(c):
    emp = U(c, "employee@janamen.kz")
    with pytest.raises(NotFoundError):
        c.notifications.mark_read(emp, "n-3")
    assert c.notifications.mark_all_read(emp) == 1


# Ассистент
@pytest.mark.parametrize("q,allowed", [
    ("Сколько дней длится ежегодный отпуск?", {"vacation_policy.md", "knowledge_base#3"}),
    ("За сколько дней подавать заявку на отпуск?", {"vacation_policy.md"}),
    ("Какая максимальная сумма внепланового аванса?", {"advance_payment.md"}),
    ("Что делать если я заболел?", {"sick_leave.md", "knowledge_base#4"}),
    ("Когда сдавать авансовый отчёт по командировке?", {"business_trips.md"}),
    ("Сколько попыток на итоговый тест?", {"academy_rules.md"}),
])
def test_assistant_answers_with_source(c, q, allowed):
    out = c.assistant.ask(q)
    assert out.found, q
    assert out.sources[0].file in allowed, out.sources[0]
    assert "Согласно документу" in out.answer


@pytest.mark.parametrize("q", [
    "Какая погода завтра в Астане?",
    "Положена ли мне компенсация за спортзал?",
    "Как получить ипотеку от компании?",
])
def test_assistant_refuses_without_source(c, q):
    out = c.assistant.ask(q)
    assert not out.found and out.sources == [] and out.can_escalate


def test_escalation_flow(c):
    emp, hr = U(c, "employee@janamen.kz"), U(c, "hr@janamen.kz")
    esc = c.escalations.create(emp, "Компенсация спортзала?", None)
    assert any(n.type == NotificationType.ESCALATION_CREATED for n in c.notifications.list_for(hr))
    with pytest.raises(ForbiddenError):
        c.escalations.answer(emp, esc.id, "x")
    c.escalations.answer(hr, esc.id, "Да, до 15 000 ₸ в месяц")
    assert c.escalations.list(emp)[0].status == "answered"
    assert c.escalations.list(U(c, "employee2@janamen.kz")) == []


def test_assistant_personal_questions_use_own_zup_record(c):
    emp = U(c, "employee@janamen.kz")
    out = c.assistant.ask("Сколько у меня осталось дней отпуска?", emp)
    assert out.mode == "profile" and "21" in out.answer and out.sources[0].file == "1c-zup"
    assert "Ерлан Тулеуов" in c.assistant.ask("Кто мой руководитель?", emp).answer


def test_assistant_no_false_positive_on_partial_match(c):
    assert not c.assistant.ask("Положен ли мне отпуск на свадьбу?", U(c, "employee@janamen.kz")).found
