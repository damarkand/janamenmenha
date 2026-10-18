from __future__ import annotations

from datetime import date
from typing import Callable

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.integrations.base import DocumentWorkflow, PersonnelSystem
from app.models.domain import (
    AdvanceDetails, HistoryEntry, HRRequest, NotificationType, RequestStatus, RequestType, Role, User,
    VacationDetails, utcnow,
)
from app.models.schemas import AdvanceCreate, VacationCreate
from app.repositories.memory import RequestRepository, UserRepository
from app.services import access
from app.services.notification_service import NotificationService

TYPE_LABEL = {RequestType.VACATION: "Отпуск", RequestType.ADVANCE: "Аванс",
              RequestType.SICK_LEAVE: "Больничный", RequestType.OTHER: "Другое"}
STATUS_LABEL = {RequestStatus.PENDING: "на рассмотрении", RequestStatus.APPROVED: "одобрена",
                RequestStatus.REJECTED: "отклонена", RequestStatus.CANCELLED: "отменена"}
ACTIVE = {RequestStatus.PENDING, RequestStatus.APPROVED}


class RequestService:
    def __init__(self, repo: RequestRepository, users: UserRepository, personnel: PersonnelSystem,
                 docflow: DocumentWorkflow, notifier: NotificationService, settings: Settings,
                 today: Callable[[], date] = date.today):
        self._repo = repo
        self._users = users
        self._personnel = personnel
        self._docflow = docflow
        self._notifier = notifier
        self._settings = settings
        self._today = today

    # Чтение
    def list(self, actor: User, scope: str = "mine", status: RequestStatus | None = None,
             type_: RequestType | None = None) -> list[HRRequest]:
        if scope == "mine":
            ids = {actor.id}
        elif scope == "team":
            ids = access.team_ids(actor, self._users)
        elif scope == "all":
            if actor.role != Role.HR:
                raise ForbiddenError("Просмотр всех заявок доступен только HR")
            ids = {u.id for u in self._users.list()}
        else:
            raise BusinessRuleError("scope должен быть mine | team | all")
        items = [r for r in self._repo.for_users(ids)
                 if (status is None or r.status == status) and (type_ is None or r.type == type_)]
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def get(self, actor: User, request_id: str) -> HRRequest:
        req = self._repo.get(request_id)
        requester = self._users.get(req.user_id) if req else None
        if not req or not requester or not access.can_view_user(actor, requester):
            raise NotFoundError("Заявка не найдена")
        return req

    # Действия
    def create_vacation(self, actor: User, data: VacationCreate) -> HRRequest:
        if data.end_date < data.start_date:
            raise BusinessRuleError("Дата окончания раньше даты начала")
        if data.start_date < self._today():
            raise BusinessRuleError("Нельзя оформить отпуск задним числом")
        days = (data.end_date - data.start_date).days + 1

        for r in self._repo.by_user(actor.id, RequestType.VACATION, ACTIVE):
            v = r.vacation
            if v and data.start_date <= v.end_date and v.start_date <= data.end_date:
                raise ConflictError(f"Период пересекается с заявкой {r.id}")

        available = self._personnel.get_employee(actor.id).vacation_days_left - self._reserved_days(actor.id)
        if days > available:
            raise BusinessRuleError(f"Недостаточно дней отпуска: запрошено {days}, доступно {available}")

        req = HRRequest(id=self._repo.next_id(), type=RequestType.VACATION, user_id=actor.id,
                        vacation=VacationDetails(start_date=data.start_date, end_date=data.end_date,
                                                 days=days, comment=data.comment))
        return self._open(actor, req)

    def create_advance(self, actor: User, data: AdvanceCreate) -> HRRequest:
        if self._repo.by_user(actor.id, RequestType.ADVANCE, {RequestStatus.PENDING}):
            raise ConflictError("У вас уже есть заявка на аванс на рассмотрении")
        limit = self._personnel.get_employee(actor.id).salary * self._settings.advance_max_percent // 100
        if data.amount > limit:
            raise BusinessRuleError(f"Сумма превышает лимит аванса ({limit} ₸, "
                                    f"{self._settings.advance_max_percent}% оклада)")
        req = HRRequest(id=self._repo.next_id(), type=RequestType.ADVANCE, user_id=actor.id,
                        advance=AdvanceDetails(amount=data.amount, reason=data.reason))
        return self._open(actor, req)

    CERTIFICATES = {
        "employment": "Справка с места работы",
        "salary": "Справка о заработной плате",
        "vacation_balance": "Справка об остатке отпуска",
        "other": "Другой документ",
    }

    def create_certificate(self, actor: User, kind: str, comment: str | None = None) -> HRRequest:
        if kind not in self.CERTIFICATES:
            raise BusinessRuleError("Неизвестный вид справки")
        text = self.CERTIFICATES[kind] + (f". {comment.strip()}" if comment and comment.strip() else "")
        req = HRRequest(id=self._repo.next_id(), type=RequestType.OTHER, user_id=actor.id, comment=text)
        req.history.append(HistoryEntry(actor_id=actor.id, action="created", to_status=RequestStatus.PENDING))
        self._repo.add(req)
        for hr in self._users.by_role(Role.HR):
            if hr.id != actor.id:
                self._notifier.notify(hr.id, NotificationType.REQUEST_CREATED, "Запрос справки",
                                      f"{actor.full_name}: {text}", link=f"/requests/{req.id}")
        return req

    def approve(self, actor: User, request_id: str, comment: str | None = None) -> HRRequest:
        req, requester = self._for_decision(actor, request_id)

        if req.type == RequestType.VACATION and req.vacation:
            v = req.vacation
            req.external_refs["zup_doc_id"] = self._personnel.register_vacation(
                requester.id, v.start_date, v.end_date, v.days)
            doc = self._docflow.create_document(
                "vacation_order", requester.id, f"Приказ об отпуске: {requester.full_name}",
                {"start_date": v.start_date.isoformat(), "end_date": v.end_date.isoformat(), "days": v.days})
        elif req.type == RequestType.ADVANCE and req.advance:
            a = req.advance
            req.external_refs["zup_doc_id"] = self._personnel.register_advance(requester.id, a.amount)
            doc = self._docflow.create_document(
                "advance_application", requester.id, f"Заявление на аванс: {requester.full_name}",
                {"amount": a.amount})
        else:
            doc = None
        if doc:
            req.external_refs["documentolog_doc_id"] = doc.id

        return self._transition(actor, req, RequestStatus.APPROVED, "approved", comment)

    def reject(self, actor: User, request_id: str, comment: str | None) -> HRRequest:
        if not comment or not comment.strip():
            raise BusinessRuleError("Укажите причину отклонения")
        req, _ = self._for_decision(actor, request_id)
        return self._transition(actor, req, RequestStatus.REJECTED, "rejected", comment)

    def cancel(self, actor: User, request_id: str) -> HRRequest:
        req = self.get(actor, request_id)
        if req.user_id != actor.id:
            raise ForbiddenError("Отменить можно только свою заявку")
        if req.status != RequestStatus.PENDING:
            raise ConflictError("Отменить можно только заявку на рассмотрении")
        return self._transition(actor, req, RequestStatus.CANCELLED, "cancelled", None, notify_owner=False)

    # Вспомогательные
    def _reserved_days(self, user_id: str) -> int:
        return sum(r.vacation.days for r in self._repo.by_user(user_id, RequestType.VACATION, {RequestStatus.PENDING})
                   if r.vacation)

    def approvers_for(self, requester: User) -> list[User]:
        manager = self._users.get(requester.manager_id) if requester.manager_id else None
        if manager:
            return [manager]
        return [u for u in self._users.by_role(Role.HR) if u.id != requester.id]

    def _open(self, actor: User, req: HRRequest) -> HRRequest:
        req.history.append(HistoryEntry(actor_id=actor.id, action="created", to_status=RequestStatus.PENDING))
        self._repo.add(req)
        for approver in self.approvers_for(actor):
            self._notifier.notify(approver.id, NotificationType.REQUEST_CREATED,
                                  f"Новая заявка: {TYPE_LABEL[req.type]}",
                                  f"{actor.full_name} подал(а) заявку {req.id}", link=f"/requests/{req.id}")
        return req

    def _for_decision(self, actor: User, request_id: str) -> tuple[HRRequest, User]:
        req = self.get(actor, request_id)
        requester = self._users.get(req.user_id)
        if not access.can_decide_request(actor, req, requester):
            raise ForbiddenError("Нет прав на согласование этой заявки")
        if req.status != RequestStatus.PENDING:
            raise ConflictError(f"Заявка уже {STATUS_LABEL[req.status]}")
        return req, requester

    def _transition(self, actor: User, req: HRRequest, to: RequestStatus, action: str,
                    comment: str | None, notify_owner: bool = True) -> HRRequest:
        req.history.append(HistoryEntry(actor_id=actor.id, action=action, from_status=req.status,
                                        to_status=to, comment=comment))
        req.status = to
        req.updated_at = utcnow()
        if to in (RequestStatus.APPROVED, RequestStatus.REJECTED):
            req.decided_by = actor.id
        self._repo.save(req)
        if notify_owner:
            msg = f"Заявка {req.id} ({TYPE_LABEL[req.type]}) {STATUS_LABEL[to]}"
            if comment:
                msg += f". Комментарий: {comment}"
            self._notifier.notify(req.user_id, NotificationType.REQUEST_STATUS_CHANGED,
                                  f"Статус заявки: {STATUS_LABEL[to]}", msg, link=f"/requests/{req.id}")
        return req
