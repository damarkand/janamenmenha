from typing import Literal

from fastapi import APIRouter, Depends, status

from app.api.deps import get_container, get_current_user
from app.api.presenters import task_out
from app.container import Container
from app.models.domain import TaskStatus, User
from app.models.schemas import TaskCreate, TaskOut, TaskStatusIn, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Задачи"])


@router.get("", response_model=list[TaskOut], summary="Задачи: mine — мои, team — команды (руководитель/HR)")
def list_tasks(scope: Literal["mine", "team"] = "mine", status: TaskStatus | None = None, user_id: str | None = None,
               user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return [task_out(c, t) for t in c.tasks.list(user, scope, status, user_id)]


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED,
             summary="Создать задачу себе или сотруднику своей команды")
def create_task(body: TaskCreate, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return task_out(c, c.tasks.create(user, body.title, body.description, body.category, body.priority,
                                      body.due_date, body.user_id))


@router.get("/{task_id}", response_model=TaskOut, summary="Задача")
def get_task(task_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return task_out(c, c.tasks.get(user, task_id))


@router.patch("/{task_id}", response_model=TaskOut, summary="Изменить задачу")
def update_task(task_id: str, body: TaskUpdate, user: User = Depends(get_current_user),
                c: Container = Depends(get_container)):
    return task_out(c, c.tasks.update(user, task_id, **body.model_dump()))


@router.post("/{task_id}/status", response_model=TaskOut, summary="Сменить статус задачи")
def set_status(task_id: str, body: TaskStatusIn, user: User = Depends(get_current_user),
               c: Container = Depends(get_container)):
    return task_out(c, c.tasks.set_status(user, task_id, body.status))


@router.delete("/{task_id}", summary="Удалить задачу")
def delete_task(task_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    c.tasks.delete(user, task_id)
    return {"deleted": task_id}
