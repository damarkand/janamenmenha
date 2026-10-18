from datetime import timedelta

import pytest

from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.models.domain import EnrollmentStatus, RequestStatus, RequestType
from app.models.schemas import AdvanceCreate, VacationCreate
from tests.conftest import TODAY


def U(c, user_id):
    return c.users.get(user_id)


# Заявки
def test_request_list_filters_and_bad_scope(container):
    hr = U(container, "u-1")
    s = container.requests
    assert {r.id for r in s.list(hr, "all", status=RequestStatus.PENDING)} == {"req-2", "req-3"}
    assert {r.id for r in s.list(hr, "all", type_=RequestType.VACATION)} == {"req-1", "req-3"}
    with pytest.raises(BusinessRuleError):
        s.list(hr, "everything")


def test_vacation_end_before_start(container):
    with pytest.raises(BusinessRuleError):
        container.requests.create_vacation(U(container, "u-3"), VacationCreate(
            start_date=TODAY + timedelta(days=10), end_date=TODAY + timedelta(days=5)))


def test_vacation_today_is_allowed_and_one_day_counts(container):
    req = container.requests.create_vacation(U(container, "u-3"), VacationCreate(start_date=TODAY, end_date=TODAY))
    assert req.vacation.days == 1


def test_hr_approves_advance_creates_documents(container):
    req = container.requests.approve(U(container, "u-1"), "req-2", None)
    assert req.status == RequestStatus.APPROVED
    assert req.external_refs["zup_doc_id"].startswith("ZUP-ADV-")
    assert container.docflow.get_document(req.external_refs["documentolog_doc_id"]).doc_type == "advance_application"


def test_manager_cannot_decide_other_team(container):
    with pytest.raises(NotFoundError):
        container.requests.reject(U(container, "u-2"), "req-3", "нет")


def test_cancel_twice_conflict(container):
    emp2 = U(container, "u-4")
    container.requests.cancel(emp2, "req-2")
    with pytest.raises(ConflictError):
        container.requests.cancel(emp2, "req-2")


def test_cancelled_vacation_frees_reserved_days(container):
    emp2 = U(container, "u-4")
    req = container.requests.create_vacation(emp2, VacationCreate(
        start_date=TODAY + timedelta(days=5), end_date=TODAY + timedelta(days=16)))
    container.requests.cancel(emp2, req.id)
    container.requests.create_vacation(emp2, VacationCreate(
        start_date=TODAY + timedelta(days=30), end_date=TODAY + timedelta(days=41)))


def test_unknown_request_not_found(container):
    with pytest.raises(NotFoundError):
        container.requests.get(U(container, "u-1"), "req-404")


def test_approval_notifies_owner_with_comment(container):
    container.requests.approve(U(container, "u-2"), "req-2", "Ок")
    last = container.notifications.list_for(U(container, "u-4"))[0]
    assert "одобрена" in last.message and "Ок" in last.message


# Обучение
def test_catalog_and_course_lookup(container):
    assert len(container.lms.catalog()) == 4
    assert {c.id for c in container.lms.catalog("onboarding")} == {"c-1", "c-4"}
    with pytest.raises(NotFoundError):
        container.lms.get_course("c-404")


def test_enrollment_conflicts_and_missing(container):
    emp, mgr = U(container, "u-3"), U(container, "u-2")
    with pytest.raises(ConflictError):
        container.lms.enroll_self(emp, "c-1")
    with pytest.raises(ConflictError):
        container.lms.assign(mgr, "u-3", "c-2")
    with pytest.raises(NotFoundError):
        container.lms.assign(mgr, "u-404", "c-3")
    with pytest.raises(NotFoundError):
        container.lms.start(emp, "c-3")


def test_progress_rules(container):
    emp = U(container, "u-3")
    with pytest.raises(BusinessRuleError):
        container.lms.update_progress(emp, "c-2", 10)
    with pytest.raises(ConflictError):
        container.lms.update_progress(emp, "c-1", 100)


def test_test_rules(container):
    emp = U(container, "u-3")
    with pytest.raises(BusinessRuleError):
        container.lms.submit_test(emp, "c-2", [0, 1])
    with pytest.raises(ConflictError):
        container.lms.submit_test(emp, "c-1", [1, 0, 1])
    container.lms.enroll_self(emp, "c-4")
    with pytest.raises(BusinessRuleError):
        container.lms.submit_test(emp, "c-4", [])


def test_best_score_is_kept(container):
    emp = U(container, "u-3")
    container.lms.submit_test(emp, "c-2", [2, 0, 0, 0, 0])
    r = container.lms.submit_test(emp, "c-2", [0, 0, 0, 0, 0])
    assert r.score == 20 and not r.passed
    assert container.enrollment_repo.find("u-3", "c-2").best_score == 40


def test_self_enrolled_completion_notifies_only_user(container):
    emp, mgr = U(container, "u-3"), U(container, "u-2")
    before = len(container.notifications.list_for(mgr))
    container.lms.enroll_self(emp, "c-4")
    assert container.lms.update_progress(emp, "c-4", 100).status == EnrollmentStatus.COMPLETED
    assert len(container.notifications.list_for(mgr)) == before


def test_hr_team_progress_sees_all(container):
    assert len(container.lms.team_progress(U(container, "u-1"))) == 4
    with pytest.raises(ForbiddenError):
        container.lms.team_progress(U(container, "u-3"))


# Профили и уведомления
def test_profile_unknown_user(container):
    with pytest.raises(NotFoundError):
        container.profiles.get_profile(U(container, "u-1"), "u-404")


def test_profile_of_other_user_hides_unread_count(container):
    p = container.profiles.get_profile(U(container, "u-1"), "u-3")
    assert p.unread_notifications == 0 and p.role_label == "Работник"


def test_profile_lists_assigned_courses(container):
    p = container.profiles.get_profile(U(container, "u-3"), "u-3")
    assert {c.course_id for c in p.assigned_courses} == {"c-1", "c-2"} and p.unread_notifications == 1


def test_notifications_unread_filter(container):
    emp = U(container, "u-3")
    assert [n.id for n in container.notifications.list_for(emp, unread_only=True)] == ["n-2"]
    container.notifications.mark_read(emp, "n-2")
    assert container.notifications.list_for(emp, unread_only=True) == []
    assert container.notifications.mark_all_read(emp) == 0
