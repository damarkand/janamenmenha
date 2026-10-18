from __future__ import annotations

from app.container import Container
from app.models.domain import Course, Enrollment, Escalation, HRRequest, Notification, Task, TaskStatus, TimeEntry, WorkSchedule
from app.models.schemas import (
    ENROLLMENT_STATUS_LABELS, REQUEST_STATUS_LABELS, REQUEST_TYPE_LABELS, CourseDetailOut, CourseOut, EnrollmentOut,
    TASK_PRIORITY_LABELS, TASK_STATUS_LABELS, EscalationOut, NotificationOut, QuestionOut, RequestOut, ScheduleOut, TaskOut,
    TimeEntryOut, UserRef,
)
from app.services.work_service import hours_per_day

WORK_FORMAT_LABELS = {"office": "В офисе", "remote": "Удалённо", "hybrid": "Гибрид"}


def user_ref(c: Container, user_id: str | None) -> UserRef | None:
    if not user_id:
        return None
    u = c.users.get(user_id)
    return UserRef(id=u.id, full_name=u.full_name) if u else UserRef(id=user_id, full_name="—")


def request_out(c: Container, r: HRRequest) -> RequestOut:
    block = r.vacation or r.advance
    details = block.model_dump(mode="json") if block else {"comment": r.comment}
    return RequestOut(id=r.id, type=r.type, type_label=REQUEST_TYPE_LABELS[r.type], status=r.status,
                      status_label=REQUEST_STATUS_LABELS[r.status], requester=user_ref(c, r.user_id),
                      created_at=r.created_at, updated_at=r.updated_at, details=details,
                      decided_by=user_ref(c, r.decided_by), external_refs=r.external_refs, history=r.history)


def course_out(course: Course) -> CourseOut:
    return CourseOut(id=course.id, title=course.title, description=course.description, category=course.category,
                     duration_min=course.duration_min, passing_score=course.passing_score,
                     mandatory=course.mandatory, material_link=course.material_link,
                     questions_count=len(course.questions))


def course_detail_out(course: Course) -> CourseDetailOut:
    return CourseDetailOut(**course_out(course).model_dump(),
                           questions=[QuestionOut(id=q.id, text=q.text, options=q.options) for q in course.questions])


def enrollment_out(c: Container, e: Enrollment) -> EnrollmentOut:
    return EnrollmentOut(id=e.id, user=user_ref(c, e.user_id), course=course_out(c.course_repo.get(e.course_id)),
                         status=e.status, status_label=ENROLLMENT_STATUS_LABELS[e.status], progress=e.progress, best_score=e.best_score, attempts=e.attempts,
                         assigned_by=user_ref(c, e.assigned_by), assigned_at=e.assigned_at, due_date=e.due_date,
                         completed_at=e.completed_at)


def notification_out(n: Notification) -> NotificationOut:
    return NotificationOut(**n.model_dump(include={"id", "type", "title", "message", "link", "read", "created_at"}))


def escalation_out(c: Container, e: Escalation) -> EscalationOut:
    return EscalationOut(id=e.id, user=user_ref(c, e.user_id), question=e.question, context=e.context,
                         status=e.status, created_at=e.created_at, answer=e.answer,
                         answered_by=user_ref(c, e.answered_by), answered_at=e.answered_at)


def task_out(c: Container, t: Task) -> TaskOut:
    today = c.today()
    return TaskOut(id=t.id, title=t.title, description=t.description, category=t.category, status=t.status,
                   status_label=TASK_STATUS_LABELS[t.status], priority=t.priority,
                   priority_label=TASK_PRIORITY_LABELS[t.priority], due_date=t.due_date,
                   overdue=bool(t.due_date and t.due_date < today and t.status != TaskStatus.DONE),
                   assignee=user_ref(c, t.user_id), created_by=user_ref(c, t.created_by), created_at=t.created_at,
                   updated_at=t.updated_at, completed_at=t.completed_at)


def time_entry_out(e: TimeEntry) -> TimeEntryOut:
    return TimeEntryOut(**e.model_dump(include={"id", "day", "hours", "task_id", "note", "created_at"}))


def schedule_out(s: WorkSchedule) -> ScheduleOut:
    return ScheduleOut(user_id=s.id, work_days=s.work_days, start_time=s.start_time, end_time=s.end_time,
                       lunch_minutes=s.lunch_minutes, work_format=s.work_format,
                       work_format_label=WORK_FORMAT_LABELS.get(s.work_format, s.work_format),
                       hours_per_day=hours_per_day(s))
