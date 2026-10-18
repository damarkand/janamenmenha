from typing import Literal

from fastapi import APIRouter, Depends, status

from app.api.deps import get_container, get_current_user
from app.api.presenters import request_out
from app.container import Container
from app.models.domain import RequestStatus, RequestType, User
from app.models.schemas import AdvanceCreate, CertificateIn, DecisionIn, RequestOut, VacationCreate

router = APIRouter(prefix="/requests", tags=["Заявки"])


@router.post("/vacation", response_model=RequestOut, status_code=status.HTTP_201_CREATED, summary="Заявка на отпуск")
def create_vacation(body: VacationCreate, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.create_vacation(user, body))


@router.post("/advance", response_model=RequestOut, status_code=status.HTTP_201_CREATED, summary="Заявка на аванс")
def create_advance(body: AdvanceCreate, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.create_advance(user, body))


@router.post("/certificate", response_model=RequestOut, status_code=status.HTTP_201_CREATED,
             summary="Запросить справку (с места работы, о зарплате, об остатке отпуска)")
def create_certificate(body: CertificateIn, user: User = Depends(get_current_user),
                       c: Container = Depends(get_container)):
    return request_out(c, c.requests.create_certificate(user, body.kind, body.comment))


@router.get("", response_model=list[RequestOut],
            summary="Список заявок: mine — свои, team — подчинённых (руководитель/HR), all — все (HR)")
def list_requests(scope: Literal["mine", "team", "all"] = "mine", status: RequestStatus | None = None,
                  type: RequestType | None = None,
                  user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return [request_out(c, r) for r in c.requests.list(user, scope, status, type)]


@router.get("/{request_id}", response_model=RequestOut, summary="Заявка с историей")
def get_request(request_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.get(user, request_id))


@router.post("/{request_id}/approve", response_model=RequestOut, summary="Одобрить (руководитель сотрудника или HR)")
def approve(request_id: str, body: DecisionIn | None = None,
            user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.approve(user, request_id, body.comment if body else None))


@router.post("/{request_id}/reject", response_model=RequestOut, summary="Отклонить (комментарий обязателен)")
def reject(request_id: str, body: DecisionIn,
           user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.reject(user, request_id, body.comment))


@router.post("/{request_id}/cancel", response_model=RequestOut, summary="Отменить свою заявку")
def cancel(request_id: str, user: User = Depends(get_current_user), c: Container = Depends(get_container)):
    return request_out(c, c.requests.cancel(user, request_id))
