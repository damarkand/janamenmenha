from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"


class RequestType(str, Enum):
    VACATION = "vacation"
    ADVANCE = "advance"
    SICK_LEAVE = "sick_leave"
    OTHER = "other"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EnrollmentStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class NotificationType(str, Enum):
    REQUEST_CREATED = "request_created"
    REQUEST_STATUS_CHANGED = "request_status_changed"
    COURSE_ASSIGNED = "course_assigned"
    COURSE_COMPLETED = "course_completed"
    ESCALATION_CREATED = "escalation_created"
    ESCALATION_ANSWERED = "escalation_answered"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    GENERAL = "general"


# Сотрудники
class User(BaseModel):
    id: str
    email: str
    password_hash: str
    role: Role
    full_name: str
    company: str
    position: str
    department: str
    manager_id: str | None = None
    hire_date: date | None = None
    vacation_days_left: int
    salary: int
    personnel_number: str


# Заявки
class VacationDetails(BaseModel):
    start_date: date
    end_date: date
    days: int
    comment: str | None = None


class AdvanceDetails(BaseModel):
    amount: int
    reason: str | None = None


class HistoryEntry(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    actor_id: str
    action: str
    from_status: RequestStatus | None = None
    to_status: RequestStatus
    comment: str | None = None


class HRRequest(BaseModel):
    id: str
    type: RequestType
    user_id: str
    status: RequestStatus = RequestStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    vacation: VacationDetails | None = None
    advance: AdvanceDetails | None = None
    comment: str | None = None
    decided_by: str | None = None
    external_refs: dict[str, str] = Field(default_factory=dict)
    history: list[HistoryEntry] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    text: str
    options: list[str]
    correct_index: int


class Course(BaseModel):
    id: str
    title: str
    description: str
    category: str
    duration_min: int
    passing_score: int = 70
    mandatory: bool = False
    material_link: str | None = None
    questions: list[Question] = Field(default_factory=list)


class Enrollment(BaseModel):
    id: str
    user_id: str
    course_id: str
    status: EnrollmentStatus = EnrollmentStatus.NOT_STARTED
    progress: int = 0
    best_score: int | None = None
    attempts: int = 0
    assigned_by: str | None = None
    assigned_at: datetime | None = Field(default_factory=utcnow)
    due_date: date | None = None
    completed_at: datetime | None = None


# Уведомления
class Notification(BaseModel):
    id: str
    user_id: str
    type: NotificationType
    title: str
    message: str
    link: str | None = None
    read: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Escalation(BaseModel):
    id: str
    user_id: str
    question: str
    context: str | None = None
    status: str = "open"
    created_at: datetime = Field(default_factory=utcnow)
    answer: str | None = None
    answered_by: str | None = None
    answered_at: datetime | None = None


# Задачи
class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(BaseModel):
    id: str
    user_id: str
    title: str
    description: str = ""
    category: str = "Общее"
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


# Учёт времени
class TimeEntry(BaseModel):
    id: str
    user_id: str
    day: date
    hours: float
    task_id: str | None = None
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# График работы
class WorkSchedule(BaseModel):
    id: str
    work_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    start_time: str = "09:00"
    end_time: str = "18:00"
    lunch_minutes: int = 60
    work_format: str = "office"
