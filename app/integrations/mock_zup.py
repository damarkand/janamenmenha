from __future__ import annotations

from datetime import date
from itertools import count

from app.core.errors import IntegrationError, NotFoundError
from app.integrations.base import EmployeeRecord, PersonnelSystem
from app.repositories.memory import UserRepository


class MockZupClient(PersonnelSystem):
    def __init__(self, users: UserRepository):
        self._users = users
        self._seq = count(1)
        self.registered: list[dict] = []

    def get_employee(self, employee_id: str) -> EmployeeRecord:
        u = self._users.get(employee_id)
        if not u:
            raise NotFoundError(f"1С:ЗУП: сотрудник {employee_id} не найден")
        return EmployeeRecord(
            employee_id=u.id, personnel_number=u.personnel_number, full_name=u.full_name,
            company=u.company, position=u.position, department=u.department, manager_id=u.manager_id,
            hire_date=u.hire_date, vacation_days_left=u.vacation_days_left, salary=u.salary,
        )

    def list_employees(self) -> list[EmployeeRecord]:
        return [self.get_employee(u.id) for u in self._users.list()]

    def register_vacation(self, employee_id: str, start: date, end: date, days: int) -> str:
        u = self._users.get(employee_id)
        if not u:
            raise NotFoundError(f"1С:ЗУП: сотрудник {employee_id} не найден")
        if u.vacation_days_left < days:
            raise IntegrationError("1С:ЗУП отклонил документ: недостаточно дней отпуска")
        u.vacation_days_left -= days
        self._users.save(u)
        doc_id = f"ZUP-VAC-{next(self._seq):05d}"
        self.registered.append({"id": doc_id, "type": "vacation", "employee_id": employee_id,
                                "start": start.isoformat(), "end": end.isoformat(), "days": days})
        return doc_id

    def register_advance(self, employee_id: str, amount: int) -> str:
        doc_id = f"ZUP-ADV-{next(self._seq):05d}"
        self.registered.append({"id": doc_id, "type": "advance", "employee_id": employee_id, "amount": amount})
        return doc_id
