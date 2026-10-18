from __future__ import annotations

from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.models.domain import Course, Enrollment, EnrollmentStatus, NotificationType, User, utcnow
from app.models.schemas import TestResultOut
from app.repositories.memory import CourseRepository, EnrollmentRepository, UserRepository
from app.services import access
from app.services.notification_service import NotificationService


class LmsService:
    def __init__(self, courses: CourseRepository, enrollments: EnrollmentRepository, users: UserRepository,
                 notifier: NotificationService):
        self._courses = courses
        self._enrollments = enrollments
        self._users = users
        self._notifier = notifier

    # Каталог
    def catalog(self, category: str | None = None) -> list[Course]:
        return sorted(self._courses.list(lambda c: category is None or c.category == category), key=lambda c: c.title)

    def get_course(self, course_id: str) -> Course:
        c = self._courses.get(course_id)
        if not c:
            raise NotFoundError("Курс не найден")
        return c

    # Записи на курсы
    def my_enrollments(self, actor: User) -> list[Enrollment]:
        return self._enrollments.by_user(actor.id)

    def team_progress(self, actor: User, user_id: str | None = None) -> list[Enrollment]:
        ids = access.team_ids(actor, self._users)
        if user_id:
            if user_id not in ids:
                raise ForbiddenError("Сотрудник не входит в вашу команду")
            ids = {user_id}
        return self._enrollments.list(lambda e: e.user_id in ids)

    def enroll_self(self, actor: User, course_id: str) -> Enrollment:
        self.get_course(course_id)
        if self._enrollments.find(actor.id, course_id):
            raise ConflictError("Вы уже записаны на этот курс")
        return self._enrollments.add(Enrollment(id=self._enrollments.next_id(), user_id=actor.id, course_id=course_id))

    def assign(self, actor: User, user_id: str, course_id: str, due_date=None) -> Enrollment:
        course = self.get_course(course_id)
        target = self._users.get(user_id)
        if not target:
            raise NotFoundError("Сотрудник не найден")
        if not access.can_manage_learning(actor, target):
            raise ForbiddenError("Назначать курсы можно только своей команде (или HR — всем)")
        if self._enrollments.find(user_id, course_id):
            raise ConflictError("Курс уже назначен этому сотруднику")
        e = self._enrollments.add(Enrollment(id=self._enrollments.next_id(), user_id=user_id, course_id=course_id,
                                             assigned_by=actor.id, due_date=due_date))
        due = f" до {due_date.isoformat()}" if due_date else ""
        self._notifier.notify(user_id, NotificationType.COURSE_ASSIGNED, "Назначен новый курс",
                              f"{actor.full_name} назначил(а) курс «{course.title}»{due}", link=f"/academy/{course_id}")
        return e

    def start(self, actor: User, course_id: str) -> Enrollment:
        e = self._own(actor, course_id)
        if e.status == EnrollmentStatus.NOT_STARTED:
            e.status = EnrollmentStatus.IN_PROGRESS
            self._enrollments.save(e)
        return e

    def update_progress(self, actor: User, course_id: str, progress: int) -> Enrollment:
        e = self._own(actor, course_id)
        course = self.get_course(course_id)
        if e.status == EnrollmentStatus.COMPLETED:
            raise ConflictError("Курс уже завершён")
        if progress < e.progress:
            raise BusinessRuleError("Прогресс не может уменьшаться")
        e.status = EnrollmentStatus.IN_PROGRESS
        if course.questions:
            e.progress = min(progress, 99)
        else:
            e.progress = progress
            if progress == 100:
                self._complete(e, course)
        return self._enrollments.save(e)

    def submit_test(self, actor: User, course_id: str, answers: list[int]) -> TestResultOut:
        e = self._own(actor, course_id)
        course = self.get_course(course_id)
        if not course.questions:
            raise BusinessRuleError("У курса нет теста")
        if e.status == EnrollmentStatus.COMPLETED:
            raise ConflictError("Тест уже успешно сдан")
        if len(answers) != len(course.questions):
            raise BusinessRuleError(f"Ожидается {len(course.questions)} ответов, получено {len(answers)}")

        correct = sum(1 for q, a in zip(course.questions, answers) if q.correct_index == a)
        score = round(correct * 100 / len(course.questions))
        passed = score >= course.passing_score

        e.attempts += 1
        e.best_score = max(e.best_score or 0, score)
        e.status = EnrollmentStatus.IN_PROGRESS
        if passed:
            self._complete(e, course)
        self._enrollments.save(e)
        return TestResultOut(score=score, correct=correct, total=len(course.questions), passed=passed,
                             passing_score=course.passing_score, status=e.status, attempts=e.attempts)

    # Вспомогательные
    def _own(self, actor: User, course_id: str) -> Enrollment:
        e = self._enrollments.find(actor.id, course_id)
        if not e:
            raise NotFoundError("Вы не записаны на этот курс")
        return e

    def _complete(self, e: Enrollment, course: Course) -> None:
        e.status = EnrollmentStatus.COMPLETED
        e.progress = 100
        e.completed_at = utcnow()
        user = self._users.get(e.user_id)
        self._notifier.notify(e.user_id, NotificationType.COURSE_COMPLETED, "Курс завершён",
                              f"Поздравляем! Курс «{course.title}» пройден", link=f"/academy/{course.id}")
        if e.assigned_by and e.assigned_by != e.user_id:
            self._notifier.notify(e.assigned_by, NotificationType.COURSE_COMPLETED, "Сотрудник завершил курс",
                                  f"{user.full_name} завершил(а) курс «{course.title}»", link=f"/academy/{course.id}")
