from datetime import date, timedelta

from fastapi import APIRouter, Depends, status

from app.api.deps import get_container, get_current_user
from app.api.presenters import schedule_out, time_entry_out
from app.container import Container
from app.models.domain import User
from app.models.schemas import ScheduleOut, ScheduleUpdate, TimeEntryCreate, TimeEntryOut

router = APIRouter(tags=["График и учёт времени"])


@router.get("/schedule", response_model=ScheduleOut, summary="График работы (свой или сотрудника команды)")
def get_schedule(user_id: str | None = None, user: User = Depends(get_current_user),
                 c: Container = Depends(get_container)):
    return schedule_out(c.schedules.get(user, user_id))


@router.put("/schedule/{user_id}", response_model=ScheduleOut, summary="Изменить график сотрудника (только HR)")
def update_schedule(user_id: str, body: ScheduleUpdate, user: User = Depends(get_current_user),
                    c: Container = Depends(get_container)):
    return schedule_out(c.schedules.update(user, user_id, **body.model_dump()))


@router.get("/schedule/calendar", summary="Рабочий календарь на месяц: дни, праздники, отпуска, часы, сроки задач")
def get_calendar(month: str | None = None, user_id: str | None = None, user: User = Depends(get_current_user),
                 c: Container = Depends(get_container)):
    data = c.schedules.calendar(user, month, user_id)
    data["schedule"] = schedule_out(data["schedule"]).model_dump()
    return data


@router.get("/time", response_model=list[TimeEntryOut], summary="Мои отметки времени за период")
def list_time(start: date | None = None, end: date | None = None, user: User = Depends(get_current_user),
              c: Container = Depends(get_container)):
    end = end or c.today()
    start = start or end - timedelta(days=30)
    return [time_entry_out(e) for e in c.time.list(user, start, end)]


@router.post("/time", response_model=TimeEntryOut, status_code=status.HTTP_201_CREATED, summary="Отметить часы")
def log_time(body: TimeEntryCreate, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return time_entry_out(c.time.log(user, body.day, body.hours, body.task_id, body.note))


@router.delete("/time/{entry_id}", summary="Удалить отметку времени")
def delete_time(entry_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    c.time.delete(user, entry_id)
    return {"deleted": entry_id}
