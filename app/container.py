from __future__ import annotations

from datetime import date
from typing import Callable

from app.core.config import Settings
from app.integrations.factory import build_document_workflow, build_personnel_system
from app.repositories.memory import (
    CourseRepository, EnrollmentRepository, EscalationRepository, NotificationRepository, RequestRepository,
    ScheduleRepository, TaskRepository, TimeEntryRepository, UserRepository,
)
from app.repositories.seed import load_holidays, load_seed, load_work_seed
from app.services.assistant_service import AssistantService, EscalationService
from app.services.auth_service import AuthService
from app.services.knowledge_base import KnowledgeBase
from app.services.llm import build_engine
from app.services.lms_service import LmsService
from app.services.notification_service import NotificationService
from app.services.profile_service import ProfileService
from app.services.request_service import RequestService
from app.services.work_service import DashboardService, ScheduleService, TaskService, TimeService


class Container:
    def __init__(self, settings: Settings, today: Callable[[], date] = date.today):
        self.settings = settings
        self.today = today

        if settings.storage == "sqlite":
            self._build_sqlite_repositories()
        elif settings.storage == "memory":
            self._build_memory_repositories()
        else:
            raise ValueError(f"Неизвестное хранилище STORAGE={settings.storage!r}: ожидается sqlite или memory")

        self.personnel = build_personnel_system(settings, self.users)
        self.docflow = build_document_workflow(settings)

        # Сервисы
        self.notifications = NotificationService(self.notification_repo)
        self.auth = AuthService(self.users, settings)
        self.profiles = ProfileService(self.users, self.personnel, self.enrollment_repo, self.course_repo,
                                       self.notifications, settings)
        self.requests = RequestService(self.request_repo, self.users, self.personnel, self.docflow,
                                       self.notifications, settings, today=today)
        self.lms = LmsService(self.course_repo, self.enrollment_repo, self.users, self.notifications)
        self._file_kb = KnowledgeBase.from_dir(settings.kb_dir)
        self.escalations = EscalationService(self.escalation_repo, self.users, self.notifications)

        self.ai = build_engine(settings)
        self.assistant = AssistantService(self.current_kb, settings, self.ai, personnel=self.personnel, users=self.users,
                                          tasks_repo=self.task_repo, time_repo=self.time_repo, today=today)
        self.holidays = load_holidays(settings.data_dir)
        self.tasks = TaskService(self.task_repo, self.users, self.notifications, today=today)
        self.time = TimeService(self.time_repo, self.task_repo, today=today)
        self.schedules = ScheduleService(self.schedule_repo, self.users, self.request_repo, self.time_repo,
                                         self.task_repo, self.holidays, today=today)
        self.dashboard = DashboardService(self.users, self.tasks, self.task_repo, self.time_repo, self.schedules,
                                          self.enrollment_repo, self.course_repo, self.request_repo, self.holidays,
                                          today=today)

    def current_kb(self) -> KnowledgeBase:
        if self.settings.storage != "sqlite":
            return self._file_kb
        from app.repositories.sqlite import load_qa_rows
        return KnowledgeBase(self._file_kb.chunks + KnowledgeBase.chunks_from_qa(load_qa_rows()))

    def _build_memory_repositories(self) -> None:
        seed = load_seed(self.settings.data_dir)
        self.users = UserRepository("u", seed["users"])
        self.request_repo = RequestRepository("req", seed["requests"])
        self.course_repo = CourseRepository("c", seed["courses"])
        self.enrollment_repo = EnrollmentRepository("enr", seed["enrollments"])
        self.notification_repo = NotificationRepository("n", seed["notifications"])
        self.escalation_repo = EscalationRepository("esc")
        work = load_work_seed(self.settings.data_dir, self.today(), {u.id for u in seed["users"]})
        self.task_repo = TaskRepository("t", work["tasks"])
        self.time_repo = TimeEntryRepository("te", work["time_entries"])
        self.schedule_repo = ScheduleRepository("u", work["schedules"])

    def _build_sqlite_repositories(self) -> None:
        from app.repositories import sqlite as s
        s.init_storage(self.settings, self.today())
        self.users = s.SqliteUserRepository(self.settings.default_salary)
        self.request_repo = s.SqliteRequestRepository()
        self.course_repo = s.SqliteCourseRepository()
        self.enrollment_repo = s.SqliteEnrollmentRepository()
        self.notification_repo = s.SqliteNotificationRepository()
        self.escalation_repo = s.SqliteEscalationRepository()
        self.task_repo = s.SqliteTaskRepository()
        self.time_repo = s.SqliteTimeEntryRepository()
        self.schedule_repo = s.SqliteScheduleRepository()
