from fastapi import APIRouter, Depends, status

from app.api.deps import get_container, get_current_user, require_roles
from app.api.presenters import course_detail_out, course_out, enrollment_out
from app.container import Container
from app.models.domain import Role, User
from app.models.schemas import (
    AssignCourseIn, CourseDetailOut, CourseOut, EnrollmentOut, ProgressIn, TestResultOut, TestSubmitIn,
)

router = APIRouter(prefix="/academy", tags=["Jana Academy (обучение)"])


@router.get("/courses", response_model=list[CourseOut], summary="Каталог курсов")
def catalog(category: str | None = None, _: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return [course_out(x) for x in c.lms.catalog(category)]


@router.get("/courses/{course_id}", response_model=CourseDetailOut, summary="Курс с вопросами теста (без ответов)")
def course(course_id: str, _: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return course_detail_out(c.lms.get_course(course_id))


@router.post("/courses/{course_id}/enroll", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED,
             summary="Записаться на курс самостоятельно")
def enroll(course_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return enrollment_out(c, c.lms.enroll_self(user, course_id))


@router.get("/my", response_model=list[EnrollmentOut], summary="Мои курсы и прогресс")
def my_courses(user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return [enrollment_out(c, e) for e in c.lms.my_enrollments(user)]


@router.post("/my/{course_id}/start", response_model=EnrollmentOut, summary="Начать курс")
def start(course_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return enrollment_out(c, c.lms.start(user, course_id))


@router.patch("/my/{course_id}/progress", response_model=EnrollmentOut, summary="Обновить прогресс (0–100)")
def progress(course_id: str, body: ProgressIn, user: User = Depends(get_current_user),
             c: Container = Depends(get_container)):
    return enrollment_out(c, c.lms.update_progress(user, course_id, body.progress))


@router.post("/my/{course_id}/test", response_model=TestResultOut, summary="Сдать итоговый тест")
def submit_test(course_id: str, body: TestSubmitIn, user: User = Depends(get_current_user),
                c: Container = Depends(get_container)):
    return c.lms.submit_test(user, course_id, body.answers)


@router.post("/assignments", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED,
             summary="Назначить курс сотруднику (руководитель — своей команде, HR — всем)")
def assign(body: AssignCourseIn, user: User = Depends(require_roles(Role.MANAGER, Role.HR)),
           c: Container = Depends(get_container)):
    return enrollment_out(c, c.lms.assign(user, body.user_id, body.course_id, body.due_date))


@router.get("/team-progress", response_model=list[EnrollmentOut], summary="Прогресс обучения команды")
def team_progress(user_id: str | None = None, user: User = Depends(require_roles(Role.MANAGER, Role.HR)),
                  c: Container = Depends(get_container)):
    return [enrollment_out(c, e) for e in c.lms.team_progress(user, user_id)]
