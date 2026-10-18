from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import (
    EnrollmentStatus, HistoryEntry, NotificationType, RequestStatus, RequestType, Role, TaskPriority, TaskStatus,
)

ROLE_LABELS = {Role.EMPLOYEE: "Работник", Role.MANAGER: "Руководитель", Role.HR: "HR / администратор"}
REQUEST_TYPE_LABELS = {RequestType.VACATION: "Отпуск", RequestType.ADVANCE: "Аванс",
                       RequestType.SICK_LEAVE: "Больничный", RequestType.OTHER: "Другое"}
REQUEST_STATUS_LABELS = {RequestStatus.PENDING: "На рассмотрении", RequestStatus.APPROVED: "Одобрена",
                         RequestStatus.REJECTED: "Отклонена", RequestStatus.CANCELLED: "Отменена"}
ENROLLMENT_STATUS_LABELS = {EnrollmentStatus.NOT_STARTED: "Не начат", EnrollmentStatus.IN_PROGRESS: "В процессе",
                            EnrollmentStatus.COMPLETED: "Завершён"}


def _examples(*items: dict) -> ConfigDict:
    return ConfigDict(json_schema_extra={"examples": list(items)})


# Авторизация
class LoginIn(BaseModel):
    model_config = _examples({"email": "employee@janamen.kz", "password": "Passw0rd!"})
    email: str = Field(description="Рабочий email")
    password: str = Field(description="Пароль")


class TokenOut(BaseModel):
    access_token: str = Field(description="JWT-токен: вставьте его в Authorize")
    token_type: str = Field(default="bearer", description="Тип токена")
    expires_in: int = Field(description="Срок действия токена, секунд")
    role: Role = Field(description="Роль: employee — работник, manager — руководитель, hr — HR")
    user_id: str = Field(description="ID пользователя")


# Профиль
class UserRef(BaseModel):
    id: str = Field(description="ID сотрудника")
    full_name: str = Field(description="ФИО")


class CourseSummary(BaseModel):
    course_id: str = Field(description="ID курса")
    title: str = Field(description="Название курса")
    status: EnrollmentStatus = Field(description="Статус прохождения")
    progress: int = Field(description="Прогресс, %")
    due_date: date | None = Field(default=None, description="Срок прохождения")


class ProfileOut(BaseModel):
    id: str = Field(description="ID сотрудника")
    email: str = Field(description="Email")
    role: Role = Field(description="Роль в системе")
    role_label: str = Field(description="Роль по-русски")
    full_name: str = Field(description="ФИО")
    company: str = Field(description="Компания")
    position: str = Field(description="Должность")
    department: str = Field(description="Подразделение")
    manager: UserRef | None = Field(description="Непосредственный руководитель")
    hire_date: date | None = Field(description="Дата приёма на работу")
    vacation_days_left: int = Field(description="Остаток дней ежегодного отпуска")
    advance_limit: int | None = Field(default=None,
                                      description="Лимит аванса, ₸ (виден только самому сотруднику и HR)")
    data_source: str = Field(default="1С:ЗУП", description="Источник официальных данных")
    read_only: bool = Field(default=True, description="Официальные данные нельзя редактировать через портал")
    assigned_courses: list[CourseSummary] = Field(default=[], description="Назначенные курсы")
    unread_notifications: int = Field(default=0, description="Количество непрочитанных уведомлений")


class TeamMemberOut(BaseModel):
    id: str = Field(description="ID сотрудника")
    full_name: str = Field(description="ФИО")
    position: str = Field(description="Должность")
    department: str = Field(description="Подразделение")
    role: Role = Field(description="Роль")
    hire_date: date | None = Field(description="Дата приёма")
    vacation_days_left: int = Field(description="Остаток дней отпуска")


# Заявки
class VacationCreate(BaseModel):
    model_config = _examples({"start_date": "2026-11-09", "end_date": "2026-11-13", "comment": "Семейные дела"})
    start_date: date = Field(description="Первый день отпуска (ГГГГ-ММ-ДД)")
    end_date: date = Field(description="Последний день отпуска, включительно")
    comment: str | None = Field(default=None, max_length=500, description="Комментарий для руководителя")


class AdvanceCreate(BaseModel):
    model_config = _examples({"amount": 100000, "reason": "Непредвиденные расходы"})
    amount: int = Field(gt=0, description="Сумма аванса, ₸ (не больше лимита из профиля)")
    reason: str | None = Field(default=None, max_length=500, description="Причина")


class DecisionIn(BaseModel):
    model_config = _examples({"comment": "Согласовано"})
    comment: str | None = Field(default=None, max_length=500,
                                description="Комментарий (при отклонении обязателен)")


class RequestOut(BaseModel):
    id: str = Field(description="ID заявки")
    type: RequestType = Field(description="Тип: vacation — отпуск, advance — аванс, sick_leave — больничный, other — другое")
    type_label: str = Field(description="Тип по-русски")
    status: RequestStatus = Field(description="Статус: pending / approved / rejected / cancelled")
    status_label: str = Field(description="Статус по-русски")
    requester: UserRef = Field(description="Автор заявки")
    created_at: datetime = Field(description="Дата создания")
    updated_at: datetime = Field(description="Дата последнего изменения")
    details: dict = Field(description="Детали: даты и дни для отпуска, сумма для аванса, комментарий для прочих типов")
    decided_by: UserRef | None = Field(default=None, description="Кто принял решение")
    external_refs: dict[str, str] = Field(default={}, description="ID документов в 1С:ЗУП и Documentolog")
    history: list[HistoryEntry] = Field(description="История изменений статуса")


# Jana Academy
class QuestionOut(BaseModel):
    id: str = Field(description="ID вопроса")
    text: str = Field(description="Текст вопроса")
    options: list[str] = Field(description="Варианты ответа (индексы с 0)")


class CourseOut(BaseModel):
    id: str = Field(description="ID курса")
    title: str = Field(description="Название")
    description: str = Field(description="Описание")
    category: str = Field(description="Категория")
    duration_min: int = Field(description="Длительность, минут")
    passing_score: int = Field(description="Проходной балл, %")
    mandatory: bool = Field(description="Обязательный курс")
    material_link: str | None = Field(default=None, description="Ссылка на материалы курса")
    questions_count: int = Field(description="Количество вопросов в итоговом тесте")


class CourseDetailOut(CourseOut):
    questions: list[QuestionOut] = Field(description="Вопросы теста (без правильных ответов)")


class EnrollmentOut(BaseModel):
    id: str = Field(description="ID записи на курс")
    user: UserRef = Field(description="Сотрудник")
    course: CourseOut = Field(description="Курс")
    status: EnrollmentStatus = Field(description="Статус: not_started / in_progress / completed")
    status_label: str = Field(description="Статус по-русски")
    progress: int = Field(description="Прогресс, %")
    best_score: int | None = Field(description="Лучший результат теста, %")
    attempts: int = Field(description="Количество попыток")
    assigned_by: UserRef | None = Field(description="Кто назначил (пусто — записался сам)")
    assigned_at: datetime | None = Field(description="Дата назначения")
    due_date: date | None = Field(description="Срок прохождения")
    completed_at: datetime | None = Field(description="Дата завершения")


class AssignCourseIn(BaseModel):
    model_config = _examples({"user_id": "u-4", "course_id": "c-3", "due_date": "2026-11-30"})
    user_id: str = Field(description="ID сотрудника")
    course_id: str = Field(description="ID курса")
    due_date: date | None = Field(default=None, description="Срок прохождения")


class ProgressIn(BaseModel):
    model_config = _examples({"progress": 60})
    progress: int = Field(ge=0, le=100, description="Прогресс, % (0–100, не может уменьшаться)")


class TestSubmitIn(BaseModel):
    model_config = _examples({"answers": [2, 0, 1, 1, 1]})
    answers: list[int] = Field(description="Индекс выбранного варианта для каждого вопроса, по порядку")


class TestResultOut(BaseModel):
    score: int = Field(description="Результат, %")
    correct: int = Field(description="Правильных ответов")
    total: int = Field(description="Всего вопросов")
    passed: bool = Field(description="Тест сдан")
    passing_score: int = Field(description="Проходной балл, %")
    status: EnrollmentStatus = Field(description="Статус курса после попытки")
    attempts: int = Field(description="Номер попытки")


# Уведомления
class NotificationOut(BaseModel):
    id: str = Field(description="ID уведомления")
    type: NotificationType = Field(description="Тип события")
    title: str = Field(description="Заголовок")
    message: str = Field(description="Текст")
    link: str | None = Field(description="Ссылка на объект во фронтенде")
    read: bool = Field(description="Прочитано")
    created_at: datetime = Field(description="Дата")


# HR-ассистент
class AskIn(BaseModel):
    model_config = _examples({"question": "Как перенести отпуск?", "history": []})
    question: str = Field(min_length=2, max_length=1000, description="Вопрос сотрудника")
    history: list[str] = Field(default=[], max_length=6, description="Предыдущие вопросы в этом диалоге")


class SourceOut(BaseModel):
    document: str = Field(description="Название документа")
    section: str = Field(description="Раздел")
    file: str = Field(description="Где лежит источник: файл .md или строка таблицы knowledge_base#id")
    relevance: float = Field(description="Релевантность (чем больше, тем точнее совпадение)")


class AskOut(BaseModel):
    answer: str = Field(description="Ответ ассистента")
    found: bool = Field(description="Найден ли достоверный ответ")
    confidence: str = Field(description="Уверенность: high — высокая, medium — средняя, none — ответа нет")
    mode: str = Field(description="Режим: qwen — ответ нейросети, extractive — цитата из базы, "
                                  "profile — личные данные, chat — приветствие и справка")
    sources: list[SourceOut] = Field(description="Источники ответа")
    can_escalate: bool = Field(default=True, description="Можно передать вопрос HR-специалисту")
    escalate_endpoint: str = Field(default="/api/v1/assistant/escalate", description="Куда отправить вопрос HR")


class EscalateIn(BaseModel):
    model_config = _examples({"question": "Какой дресс-код в офисе?", "context": "Ассистент не нашёл ответ"})
    question: str = Field(min_length=3, max_length=1000, description="Вопрос для HR")
    context: str | None = Field(default=None, max_length=2000, description="Дополнительный контекст")


class EscalationAnswerIn(BaseModel):
    model_config = _examples({"answer": "Деловой повседневный стиль, по пятницам — свободный."})
    answer: str = Field(min_length=1, max_length=4000, description="Ответ HR")


class EscalationOut(BaseModel):
    id: str = Field(description="ID обращения")
    user: UserRef = Field(description="Автор вопроса")
    question: str = Field(description="Вопрос")
    context: str | None = Field(description="Контекст")
    status: str = Field(description="Статус: open — открыто, answered — отвечено")
    created_at: datetime = Field(description="Дата создания")
    answer: str | None = Field(description="Ответ HR")
    answered_by: UserRef | None = Field(description="Кто ответил")
    answered_at: datetime | None = Field(description="Дата ответа")


# Задачи
TASK_STATUS_LABELS = {TaskStatus.TODO: "К выполнению", TaskStatus.IN_PROGRESS: "В работе", TaskStatus.DONE: "Готово"}
TASK_PRIORITY_LABELS = {TaskPriority.LOW: "Низкий", TaskPriority.MEDIUM: "Средний", TaskPriority.HIGH: "Высокий"}


class TaskCreate(BaseModel):
    model_config = _examples({"title": "Подготовить отчёт за месяц", "description": "", "category": "Отчётность",
                              "priority": "medium", "due_date": "2026-10-30"})
    title: str = Field(min_length=1, max_length=200, description="Название")
    description: str = Field(default="", max_length=2000, description="Описание")
    category: str = Field(default="Общее", max_length=60, description="Категория: Отчётность, Встречи, Клиенты…")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Приоритет: low / medium / high")
    due_date: date | None = Field(default=None, description="Срок")
    user_id: str | None = Field(default=None, description="Исполнитель (по умолчанию — вы сами)")


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=60)
    priority: TaskPriority | None = None
    due_date: date | None = None


class TaskStatusIn(BaseModel):
    model_config = _examples({"status": "in_progress"})
    status: TaskStatus = Field(description="todo / in_progress / done")


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    category: str
    status: TaskStatus
    status_label: str
    priority: TaskPriority
    priority_label: str
    due_date: date | None
    overdue: bool = Field(description="Срок прошёл, а задача не выполнена")
    assignee: UserRef
    created_by: UserRef | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


# Учёт времени
class TimeEntryCreate(BaseModel):
    model_config = _examples({"day": "2026-10-16", "hours": 8, "note": "Текущие задачи"})
    day: date = Field(description="День")
    hours: float = Field(gt=0, le=24, description="Часы")
    task_id: str | None = Field(default=None, description="Задача (необязательно)")
    note: str = Field(default="", max_length=300, description="Комментарий")


class TimeEntryOut(BaseModel):
    id: str
    day: date
    hours: float
    task_id: str | None
    note: str
    created_at: datetime


# График работы
class ScheduleOut(BaseModel):
    user_id: str
    work_days: list[int] = Field(description="Рабочие дни недели: 0 — пн … 6 — вс")
    start_time: str
    end_time: str
    lunch_minutes: int
    work_format: str = Field(description="office / remote / hybrid")
    work_format_label: str
    hours_per_day: float


class ScheduleUpdate(BaseModel):
    work_days: list[int] | None = None
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    lunch_minutes: int | None = Field(default=None, ge=0, le=180)
    work_format: str | None = Field(default=None, pattern=r"^(office|remote|hybrid)$")


class CertificateIn(BaseModel):
    model_config = _examples({"kind": "employment", "comment": "Для банка"})
    kind: str = Field(description="employment / salary / vacation_balance / other")
    comment: str | None = Field(default=None, max_length=500, description="Для чего нужна справка")
