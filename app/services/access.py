from __future__ import annotations

from app.core.errors import ForbiddenError
from app.models.domain import HRRequest, Role, User
from app.repositories.memory import UserRepository


def can_view_user(actor: User, target: User) -> bool:
    if actor.id == target.id or actor.role == Role.HR:
        return True
    return actor.role == Role.MANAGER and target.manager_id == actor.id


def ensure_can_view_user(actor: User, target: User) -> None:
    if not can_view_user(actor, target):
        raise ForbiddenError("Нет доступа к данным этого сотрудника")


def visible_user_ids(actor: User, users: UserRepository) -> set[str]:
    if actor.role == Role.HR:
        return {u.id for u in users.list()}
    ids = {actor.id}
    if actor.role == Role.MANAGER:
        ids |= {u.id for u in users.direct_reports(actor.id)}
    return ids


def team_ids(actor: User, users: UserRepository) -> set[str]:
    if actor.role == Role.HR:
        return {u.id for u in users.list() if u.id != actor.id}
    if actor.role == Role.MANAGER:
        return {u.id for u in users.direct_reports(actor.id)}
    raise ForbiddenError("Доступно только руководителю или HR")


def can_decide_request(actor: User, request: HRRequest, requester: User) -> bool:
    if request.user_id == actor.id:
        return False
    if actor.role == Role.HR:
        return True
    return actor.role == Role.MANAGER and requester.manager_id == actor.id


def can_manage_learning(actor: User, target: User) -> bool:
    if actor.role == Role.HR:
        return True
    return actor.role == Role.MANAGER and target.manager_id == actor.id


def can_manage(actor: User, target: User) -> bool:
    return actor.id == target.id or can_manage_learning(actor, target)
