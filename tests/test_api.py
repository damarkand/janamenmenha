import pytest

from app.container import Container
from app.main import create_app

API = "/api/v1"
EMP, EMP2, SALES = "employee@janamen.kz", "employee2@janamen.kz", "sales@janamen.kz"
MGR, MGR2, HR = "manager@janamen.kz", "manager2@janamen.kz", "hr@janamen.kz"
CORRECT_C2 = [2, 0, 1, 1, 1]


def notifications(client, headers, type_=None):
    items = client.get(f"{API}/notifications", headers=headers).json()
    return [n for n in items if type_ is None or n["type"] == type_]


# Система
def test_health(client, settings):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["integration_mode"] == "mock" and body["storage"] == settings.storage
    assert body["assistant_mode"] == "extractive" and body["kb_sections"] > 0 and body["ai_loaded"] is False


def test_site_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Digital HR" in r.text


def test_openapi_is_russian(client):
    spec = client.get("/openapi.json").json()
    assert "JanaMen" in spec["info"]["title"]
    assert {"Заявки", "Уведомления", "HR-ассистент (ИИ)"} <= {t["name"] for t in spec["tags"]}
    assert client.get("/docs").status_code == 200


# Авторизация
def test_login_success(client):
    r = client.post(f"{API}/auth/login", json={"email": HR, "password": "Passw0rd!"})
    body = r.json()
    assert r.status_code == 200 and body["role"] == "hr" and body["user_id"] == "u-1"
    assert body["token_type"] == "bearer" and body["access_token"]


@pytest.mark.parametrize("email,password", [(EMP, "wrong"), ("nobody@janamen.kz", "Passw0rd!")])
def test_login_failure(client, email, password):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401 and r.json() == {"error": "unauthorized", "message": "Неверный email или пароль"}


def test_missing_and_invalid_token(client):
    assert client.get(f"{API}/users/me").status_code == 401
    r = client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["message"] == "Недействительный токен"


def test_auth_me(client, login):
    body = client.get(f"{API}/auth/me", headers=login(MGR)).json()
    assert body["id"] == "u-2" and body["role_label"] == "Руководитель"


# Профили
def test_employee_profile(client, login):
    body = client.get(f"{API}/users/me", headers=login(EMP)).json()
    assert body["read_only"] is True and body["data_source"] == "1С:ЗУП"
    assert body["vacation_days_left"] == 21 and body["advance_limit"] == 300000
    assert body["manager"] == {"id": "u-2", "full_name": "Ерлан Тулеуов"}
    assert len(body["assigned_courses"]) == 2 and body["unread_notifications"] == 1


def test_employee_profile_scope(client, login):
    h = login(EMP)
    assert client.get(f"{API}/users/u-3", headers=h).status_code == 200
    assert client.get(f"{API}/users/u-4", headers=h).status_code == 403
    assert client.get(f"{API}/users", headers=h).status_code == 403


def test_manager_profile_scope(client, login):
    h = login(MGR)
    assert {u["id"] for u in client.get(f"{API}/users", headers=h).json()} == {"u-3", "u-4"}
    assert client.get(f"{API}/users/u-3", headers=h).json()["advance_limit"] is None
    assert client.get(f"{API}/users/u-6", headers=h).status_code == 403


def test_hr_profile_scope(client, login):
    h = login(HR)
    assert len(client.get(f"{API}/users", headers=h).json()) == 5
    assert client.get(f"{API}/users/u-6", headers=h).json()["advance_limit"] == 210000
    assert client.get(f"{API}/users/u-404", headers=h).status_code == 404


# Заявки
def test_vacation_full_flow(client, login):
    emp, mgr = login(EMP), login(MGR)
    r = client.post(f"{API}/requests/vacation", headers=emp,
                    json={"start_date": "2026-11-09", "end_date": "2026-11-13", "comment": "Семейные дела"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending" and req["status_label"] == "На рассмотрении"
    assert req["type_label"] == "Отпуск" and req["details"]["days"] == 5
    rid = req["id"]
    assert any(rid in n["message"] for n in notifications(client, mgr, "request_created"))

    assert client.post(f"{API}/requests/{rid}/approve", headers=emp).status_code == 403
    assert client.post(f"{API}/requests/{rid}/approve", headers=login(MGR2)).status_code == 404

    r = client.post(f"{API}/requests/{rid}/approve", headers=mgr, json={"comment": "Согласовано"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "approved" and body["status_label"] == "Одобрена"
    assert body["decided_by"]["id"] == "u-2"
    assert [h["action"] for h in body["history"]] == ["created", "approved"]
    assert set(body["external_refs"]) == {"zup_doc_id", "documentolog_doc_id"}

    assert client.get(f"{API}/users/me", headers=emp).json()["vacation_days_left"] == 16
    assert notifications(client, emp)[0]["type"] == "request_status_changed"
    assert client.post(f"{API}/requests/{rid}/approve", headers=mgr).status_code == 409

    hr = login(HR)
    doc_id = body["external_refs"]["documentolog_doc_id"]
    assert client.get(f"{API}/mock/documentolog/documents/{doc_id}", headers=hr).json()["doc_type"] == "vacation_order"
    journal = client.get(f"{API}/mock/1c-zup/registered-documents", headers=hr).json()
    assert journal[-1]["id"] == body["external_refs"]["zup_doc_id"]


@pytest.mark.parametrize("payload", [
    {"start_date": "2026-10-01", "end_date": "2026-10-05"},
    {"start_date": "2026-11-10", "end_date": "2026-11-05"},
    {"start_date": "2026-11-01", "end_date": "2026-12-31"},
])
def test_vacation_business_rules(client, login, payload):
    r = client.post(f"{API}/requests/vacation", headers=login(EMP), json=payload)
    assert r.status_code == 422 and r.json()["error"] == "business_rule_violation"


def test_vacation_overlap_conflict(client, login):
    h = login(EMP)
    client.post(f"{API}/requests/vacation", headers=h, json={"start_date": "2026-11-09", "end_date": "2026-11-13"})
    r = client.post(f"{API}/requests/vacation", headers=h, json={"start_date": "2026-11-12", "end_date": "2026-11-14"})
    assert r.status_code == 409


def test_advance_flow_and_reject(client, login):
    emp, mgr = login(EMP), login(MGR)
    assert client.post(f"{API}/requests/advance", headers=emp, json={"amount": 300001}).status_code == 422
    assert client.post(f"{API}/requests/advance", headers=emp, json={"amount": 0}).status_code == 422
    r = client.post(f"{API}/requests/advance", headers=emp, json={"amount": 100000, "reason": "Ремонт"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.post(f"{API}/requests/advance", headers=emp, json={"amount": 1000}).status_code == 409

    assert client.post(f"{API}/requests/{rid}/reject", headers=mgr, json={"comment": ""}).status_code == 422
    assert client.post(f"{API}/requests/{rid}/reject", headers=mgr).status_code == 422
    body = client.post(f"{API}/requests/{rid}/reject", headers=mgr, json={"comment": "Нет бюджета"}).json()
    assert body["status"] == "rejected" and body["history"][-1]["comment"] == "Нет бюджета"


def test_request_list_scopes_and_filters(client, login):
    emp, mgr, hr = login(EMP), login(MGR), login(HR)
    ids = lambda r: {x["id"] for x in r.json()}
    assert ids(client.get(f"{API}/requests", headers=emp)) == {"req-1"}
    assert client.get(f"{API}/requests?scope=team", headers=emp).status_code == 403
    assert ids(client.get(f"{API}/requests?scope=team", headers=mgr)) == {"req-1", "req-2"}
    assert client.get(f"{API}/requests?scope=all", headers=mgr).status_code == 403
    assert len(client.get(f"{API}/requests?scope=all", headers=hr).json()) == 3
    assert ids(client.get(f"{API}/requests?scope=all&status=pending", headers=hr)) == {"req-2", "req-3"}
    assert ids(client.get(f"{API}/requests?scope=all&type=vacation", headers=hr)) == {"req-1", "req-3"}
    r = client.get(f"{API}/requests?scope=everything", headers=hr)
    assert r.status_code == 422 and r.json()["error"] == "validation_error"


def test_get_request_scope(client, login):
    assert client.get(f"{API}/requests/req-1", headers=login(EMP)).json()["history"]
    assert client.get(f"{API}/requests/req-2", headers=login(EMP)).status_code == 404
    assert client.get(f"{API}/requests/req-2", headers=login(MGR)).status_code == 200
    assert client.get(f"{API}/requests/req-404", headers=login(HR)).status_code == 404


def test_cancel_request(client, login):
    assert client.post(f"{API}/requests/req-2/cancel", headers=login(MGR)).status_code == 403
    emp2 = login(EMP2)
    r = client.post(f"{API}/requests/req-2/cancel", headers=emp2)
    assert r.status_code == 200 and r.json()["status_label"] == "Отменена"
    assert client.post(f"{API}/requests/req-2/cancel", headers=emp2).status_code == 409


def test_manager_request_is_approved_by_hr(client, login):
    mgr, hr = login(MGR), login(HR)
    rid = client.post(f"{API}/requests/advance", headers=mgr, json={"amount": 50000}).json()["id"]
    assert client.post(f"{API}/requests/{rid}/approve", headers=mgr).status_code == 403
    assert any(rid in n["message"] for n in notifications(client, hr, "request_created"))
    assert client.post(f"{API}/requests/{rid}/approve", headers=hr).json()["status"] == "approved"


# Jana Academy
def test_catalog_and_course_detail(client, login):
    h = login(EMP)
    assert len(client.get(f"{API}/academy/courses", headers=h).json()) == 4
    assert {c["id"] for c in client.get(f"{API}/academy/courses?category=onboarding", headers=h).json()} == {"c-1", "c-4"}
    r = client.get(f"{API}/academy/courses/c-2", headers=h)
    assert len(r.json()["questions"]) == 5 and "correct_index" not in r.text
    assert client.get(f"{API}/academy/courses/c-404", headers=h).status_code == 404


def test_my_courses(client, login):
    items = client.get(f"{API}/academy/my", headers=login(EMP)).json()
    assert {(e["course"]["id"], e["status_label"]) for e in items} == {("c-1", "Завершён"), ("c-2", "В процессе")}


def test_self_enroll_progress_and_test(client, login):
    h = login(EMP)
    assert client.post(f"{API}/academy/courses/c-3/enroll", headers=h).status_code == 201
    assert client.post(f"{API}/academy/courses/c-3/enroll", headers=h).status_code == 409
    assert client.post(f"{API}/academy/my/c-3/start", headers=h).json()["status"] == "in_progress"
    assert client.patch(f"{API}/academy/my/c-3/progress", headers=h, json={"progress": 100}).json()["progress"] == 99
    assert client.patch(f"{API}/academy/my/c-3/progress", headers=h, json={"progress": 30}).status_code == 422
    assert client.patch(f"{API}/academy/my/c-3/progress", headers=h, json={"progress": 150}).status_code == 422
    assert client.post(f"{API}/academy/my/c-3/test", headers=h, json={"answers": [0]}).status_code == 422

    fail = client.post(f"{API}/academy/my/c-3/test", headers=h, json={"answers": [1, 0]}).json()
    assert fail == {"score": 0, "correct": 0, "total": 2, "passed": False, "passing_score": 70,
                    "status": "in_progress", "attempts": 1}
    ok = client.post(f"{API}/academy/my/c-3/test", headers=h, json={"answers": [0, 1]}).json()
    assert ok["passed"] and ok["score"] == 100 and ok["status"] == "completed" and ok["attempts"] == 2
    assert client.post(f"{API}/academy/my/c-3/test", headers=h, json={"answers": [0, 1]}).status_code == 409
    assert notifications(client, h)[0]["type"] == "course_completed"


def test_assigned_course_completion_notifies_manager(client, login):
    r = client.post(f"{API}/academy/my/c-2/test", headers=login(EMP), json={"answers": CORRECT_C2}).json()
    assert r["passed"] and r["score"] == 100
    assert notifications(client, login(MGR), "course_completed")


def test_not_enrolled_course(client, login):
    assert client.post(f"{API}/academy/my/c-4/start", headers=login(EMP2)).status_code == 404


def test_assign_course(client, login):
    mgr = login(MGR)
    r = client.post(f"{API}/academy/assignments", headers=mgr,
                    json={"user_id": "u-4", "course_id": "c-3", "due_date": "2026-11-30"})
    assert r.status_code == 201 and r.json()["assigned_by"]["id"] == "u-2" and r.json()["due_date"] == "2026-11-30"
    assert notifications(client, login(EMP2), "course_assigned")
    body = {"user_id": "u-4", "course_id": "c-3"}
    assert client.post(f"{API}/academy/assignments", headers=mgr, json=body).status_code == 409
    assert client.post(f"{API}/academy/assignments", headers=mgr, json={"user_id": "u-6", "course_id": "c-3"}).status_code == 403
    assert client.post(f"{API}/academy/assignments", headers=login(EMP), json=body).status_code == 403
    assert client.post(f"{API}/academy/assignments", headers=mgr, json={"user_id": "u-404", "course_id": "c-3"}).status_code == 404
    assert client.post(f"{API}/academy/assignments", headers=mgr, json={"user_id": "u-4", "course_id": "c-404"}).status_code == 404
    assert client.post(f"{API}/academy/assignments", headers=login(HR), json={"user_id": "u-6", "course_id": "c-3"}).status_code == 201


def test_team_progress(client, login):
    mgr = login(MGR)
    assert {e["user"]["id"] for e in client.get(f"{API}/academy/team-progress", headers=mgr).json()} == {"u-3", "u-4"}
    assert {e["user"]["id"] for e in client.get(f"{API}/academy/team-progress?user_id=u-4", headers=mgr).json()} == {"u-4"}
    assert client.get(f"{API}/academy/team-progress?user_id=u-6", headers=mgr).status_code == 403
    assert client.get(f"{API}/academy/team-progress", headers=login(EMP)).status_code == 403
    assert len(client.get(f"{API}/academy/team-progress", headers=login(HR)).json()) == 4


# Уведомления
def test_notifications_flow(client, login):
    h = login(EMP)
    assert [n["id"] for n in client.get(f"{API}/notifications", headers=h).json()] == ["n-2", "n-1"]
    assert [n["id"] for n in client.get(f"{API}/notifications?unread_only=true", headers=h).json()] == ["n-2"]
    assert client.post(f"{API}/notifications/n-2/read", headers=h).json()["read"] is True
    assert client.post(f"{API}/notifications/n-3/read", headers=h).status_code == 404
    assert client.get(f"{API}/notifications?unread_only=true", headers=h).json() == []


def test_notifications_read_all(client, login):
    h = login(MGR)
    assert client.post(f"{API}/notifications/read-all", headers=h).json() == {"updated": 1}
    assert client.get(f"{API}/notifications?unread_only=true", headers=h).json() == []


# HR-ассистент
def test_assistant_answers_with_source(client, login):
    r = client.post(f"{API}/assistant/ask", headers=login(EMP), json={"question": "Как перенести отпуск?"}).json()
    assert r["found"] and r["mode"] == "extractive" and r["confidence"] in {"high", "medium"}
    assert r["sources"][0]["file"] == "vacation_policy.md" and "Согласно документу" in r["answer"]


def test_assistant_refuses_and_offers_escalation(client, login):
    r = client.post(f"{API}/assistant/ask", headers=login(EMP), json={"question": "Какой дресс-код в офисе?"}).json()
    assert not r["found"] and r["sources"] == [] and r["can_escalate"]
    assert r["escalate_endpoint"] == "/api/v1/assistant/escalate"


def test_assistant_personal_question(client, login):
    r = client.post(f"{API}/assistant/ask", headers=login(EMP),
                    json={"question": "Сколько у меня осталось дней отпуска?"}).json()
    assert r["mode"] == "profile" and "21" in r["answer"]


def test_assistant_validation_and_auth(client, login):
    assert client.post(f"{API}/assistant/ask", json={"question": "Как перенести отпуск?"}).status_code == 401
    r = client.post(f"{API}/assistant/ask", headers=login(EMP), json={"question": "а"})
    assert r.status_code == 422 and r.json()["details"][0]["message"] == "Слишком короткое значение"


def test_escalation_over_http(client, login):
    emp, hr = login(EMP), login(HR)
    r = client.post(f"{API}/assistant/escalate", headers=emp,
                    json={"question": "Какой дресс-код в офисе?", "context": "Ассистент не нашёл ответ"})
    assert r.status_code == 201 and r.json()["status"] == "open"
    eid = r.json()["id"]
    assert notifications(client, hr, "escalation_created")
    assert [e["id"] for e in client.get(f"{API}/assistant/escalations", headers=emp).json()] == [eid]
    assert client.get(f"{API}/assistant/escalations", headers=login(EMP2)).json() == []
    assert [e["id"] for e in client.get(f"{API}/assistant/escalations?status=open", headers=hr).json()] == [eid]

    assert client.post(f"{API}/assistant/escalations/{eid}/answer", headers=emp, json={"answer": "x"}).status_code == 403
    assert client.post(f"{API}/assistant/escalations/esc-404/answer", headers=hr, json={"answer": "x"}).status_code == 404
    r = client.post(f"{API}/assistant/escalations/{eid}/answer", headers=hr, json={"answer": "Деловой стиль"})
    assert r.json()["status"] == "answered" and r.json()["answered_by"]["id"] == "u-1"
    assert notifications(client, emp)[0]["type"] == "escalation_answered"


# Заглушки интеграций
def test_mock_integrations_access(client, login):
    for email in (EMP, MGR):
        assert client.get(f"{API}/mock/1c-zup/employees", headers=login(email)).status_code == 403
    hr = login(HR)
    assert len(client.get(f"{API}/mock/1c-zup/employees", headers=hr).json()) == 6
    assert client.get(f"{API}/mock/1c-zup/employees/u-3", headers=hr).json()["personnel_number"] == "00103"
    assert client.get(f"{API}/mock/1c-zup/employees/u-404", headers=hr).status_code == 404
    assert client.get(f"{API}/mock/1c-zup/registered-documents", headers=hr).json() == []
    assert client.get(f"{API}/mock/documentolog/documents", headers=hr).json() == []
    assert client.get(f"{API}/mock/documentolog/documents/DL-404", headers=hr).status_code == 404


def test_real_integration_mode_returns_501(settings):
    from fastapi.testclient import TestClient

    settings.integration_mode = "real"
    client = TestClient(create_app(settings, Container(settings)))
    token = client.post(f"{API}/auth/login", json={"email": EMP, "password": "Passw0rd!"}).json()["access_token"]
    r = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 501 and r.json()["error"] == "not_implemented"


# Формат ошибок
def test_validation_errors_in_russian(client, login):
    r = client.post(f"{API}/requests/vacation", json={"start_date": "не дата"}, headers=login(EMP))
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error" and body["message"] == "Ошибка в данных запроса"
    messages = {d["field"]: d["message"] for d in body["details"]}
    assert messages["start_date"].startswith("Ожидается дата")
    assert messages["end_date"] == "Обязательное поле"


# Задачи
def test_tasks_over_http(client, login):
    emp, mgr = login(EMP), login(MGR)
    mine = client.get(f"{API}/tasks", headers=emp).json()
    assert len(mine) == 6 and {"status_label", "priority_label", "overdue", "assignee"} <= set(mine[0])

    r = client.post(f"{API}/tasks", headers=mgr, json={"title": "Подготовить демо", "user_id": "u-3",
                                                        "priority": "high", "due_date": "2026-10-20"})
    assert r.status_code == 201 and r.json()["assignee"]["id"] == "u-3" and r.json()["created_by"]["id"] == "u-2"
    tid = r.json()["id"]
    assert notifications(client, emp, "task_assigned")

    assert client.post(f"{API}/tasks", headers=emp, json={"title": "x", "user_id": "u-4"}).status_code == 403
    assert client.post(f"{API}/tasks", headers=emp, json={"title": ""}).status_code == 422

    r = client.post(f"{API}/tasks/{tid}/status", headers=emp, json={"status": "done"})
    assert r.json()["status_label"] == "Готово" and r.json()["completed_at"]
    assert notifications(client, mgr, "task_completed")
    assert client.post(f"{API}/tasks/{tid}/status", headers=emp, json={"status": "lost"}).status_code == 422

    r = client.patch(f"{API}/tasks/{tid}", headers=emp, json={"title": "Демо для жюри"})
    assert r.json()["title"] == "Демо для жюри"
    assert client.get(f"{API}/tasks/{tid}", headers=login(EMP2)).status_code == 404
    assert client.delete(f"{API}/tasks/{tid}", headers=emp).status_code == 403
    assert client.delete(f"{API}/tasks/{tid}", headers=mgr).json() == {"deleted": tid}

    team = client.get(f"{API}/tasks?scope=team", headers=mgr).json()
    assert {t["assignee"]["id"] for t in team} == {"u-3", "u-4"}
    assert client.get(f"{API}/tasks?scope=team", headers=emp).status_code == 403


# График и часы
def test_schedule_and_time_over_http(client, login):
    emp, hr = login(EMP), login(HR)
    s = client.get(f"{API}/schedule", headers=emp).json()
    assert s["work_format_label"] == "Гибрид" and s["hours_per_day"] == 8

    cal = client.get(f"{API}/schedule/calendar?month=2026-10", headers=emp).json()
    assert len(cal["days"]) == 31 and cal["schedule"]["start_time"] == "10:00"
    assert client.get(f"{API}/schedule/calendar?month=2026-13", headers=emp).status_code == 422
    assert client.get(f"{API}/schedule/calendar?user_id=u-4", headers=emp).status_code == 403

    r = client.post(f"{API}/time", headers=emp, json={"day": "2026-10-17", "hours": 2.5, "note": "Документы"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert client.post(f"{API}/time", headers=emp, json={"day": "2026-10-30", "hours": 1}).status_code == 422
    assert client.post(f"{API}/time", headers=emp, json={"day": "2026-10-17", "hours": 30}).status_code == 422
    entries = client.get(f"{API}/time?start=2026-10-17&end=2026-10-17", headers=emp).json()
    assert any(e["id"] == eid for e in entries)
    assert client.delete(f"{API}/time/{eid}", headers=login(EMP2)).status_code == 404
    assert client.delete(f"{API}/time/{eid}", headers=emp).status_code == 200

    assert client.put(f"{API}/schedule/u-3", headers=emp, json={"start_time": "08:00"}).status_code == 403
    r = client.put(f"{API}/schedule/u-3", headers=hr, json={"start_time": "08:00", "end_time": "17:00"})
    assert r.json()["start_time"] == "08:00" and r.json()["hours_per_day"] == 8


# Главная
def test_dashboards_over_http(client, login):
    me = client.get(f"{API}/dashboard/me", headers=login(EMP)).json()
    assert me["cards"]["open_tasks"] == 3 and len(me["charts"]["hours_by_day"]) == 14
    assert me["upcoming_tasks"] and "status_label" in me["upcoming_tasks"][0]
    assert client.get(f"{API}/dashboard/team", headers=login(EMP)).status_code == 403
    team = client.get(f"{API}/dashboard/team", headers=login(MGR)).json()
    assert team["totals"]["members"] == 2


def test_certificate_over_http(client, login):
    r = client.post(f"{API}/requests/certificate", headers=login(EMP), json={"kind": "salary", "comment": "Для визы"})
    assert r.status_code == 201 and r.json()["type"] == "other" and "о заработной плате" in r.json()["details"]["comment"]
    assert client.post(f"{API}/requests/certificate", headers=login(EMP), json={"kind": "x"}).status_code == 422


# Потоковый ответ ассистента
def test_assistant_stream_over_http(client, login):
    import json as _json
    r = client.post(f"{API}/assistant/ask/stream", headers=login(EMP), json={"question": "Как перенести отпуск?"})
    assert r.status_code == 200
    events = [_json.loads(line[5:]) for line in r.text.split("\n") if line.startswith("data:")]
    assert events[0]["type"] == "meta" and events[0]["found"] and events[-1]["type"] == "done"
    assert "Согласно документу" in "".join(e.get("text", "") for e in events)


def test_assistant_status_and_history(client, login):
    st = client.get(f"{API}/assistant/status", headers=login(EMP)).json()
    assert st["mode"] == "extractive" and st["setting"] == "off" and st["loaded"] is False
    r = client.post(f"{API}/assistant/ask", headers=login(EMP),
                    json={"question": "а частями можно?", "history": ["Можно ли разделить отпуск?"]}).json()
    assert r["found"]
