from __future__ import annotations

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.integrations.base import PersonnelSystem
from app.models.domain import Role, User
from app.models.schemas import ROLE_LABELS, CourseSummary, ProfileOut, TeamMemberOut, UserRef
from app.repositories.memory import CourseRepository, EnrollmentRepository, UserRepository
from app.services import access
from app.services.notification_service import NotificationService


class ProfileService:
    def __init__(self, users: UserRepository, personnel: PersonnelSystem, enrollments: EnrollmentRepository,
                 courses: CourseRepository, notifications: NotificationService, settings: Settings):
        self._users = users
        self._personnel = personnel
        self._enrollments = enrollments
        self._courses = courses
        self._notifications = notifications
        self._settings = settings

    def _get_user(self, user_id: str) -> User:
        u = self._users.get(user_id)
        if not u:
            raise NotFoundError("Сотрудник не найден")
        return u

    def get_profile(self, actor: User, user_id: str) -> ProfileOut:
        target = self._get_user(user_id)
        access.ensure_can_view_user(actor, target)
        rec = self._personnel.get_employee(target.id)

        manager = self._users.get(rec.manager_id) if rec.manager_id else None
        is_self_or_hr = actor.id == target.id or actor.role == Role.HR

        courses = []
        for e in self._enrollments.by_user(target.id):
            c = self._courses.get(e.course_id)
            if c:
                courses.append(CourseSummary(course_id=c.id, title=c.title, status=e.status,
                                             progress=e.progress, due_date=e.due_date))
        return ProfileOut(
            id=target.id, email=target.email, role=target.role, role_label=ROLE_LABELS[target.role],
            full_name=rec.full_name,
            company=rec.company, position=rec.position, department=rec.department,
            manager=UserRef(id=manager.id, full_name=manager.full_name) if manager else None,
            hire_date=rec.hire_date, vacation_days_left=rec.vacation_days_left,
            advance_limit=rec.salary * self._settings.advance_max_percent // 100 if is_self_or_hr else None,
            assigned_courses=courses,
            unread_notifications=self._notifications.unread_count(target.id) if actor.id == target.id else 0,
        )

    def list_visible_users(self, actor: User) -> list[TeamMemberOut]:
        ids = access.team_ids(actor, self._users)
        return [TeamMemberOut(id=u.id, full_name=u.full_name, position=u.position, department=u.department,
                              role=u.role, hire_date=u.hire_date, vacation_days_left=u.vacation_days_left)
                for u in sorted(self._users.list(lambda u: u.id in ids), key=lambda u: u.full_name)]
