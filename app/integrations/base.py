from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel


class EmployeeRecord(BaseModel):
    employee_id: str
    personnel_number: str
    full_name: str
    company: str
    position: str
    department: str
    manager_id: str | None
    hire_date: date | None
    vacation_days_left: int
    salary: int


class DocumentRef(BaseModel):
    id: str
    doc_type: str
    title: str
    status: str
    url: str | None = None


class PersonnelSystem(ABC):
    @abstractmethod
    def get_employee(self, employee_id: str) -> EmployeeRecord: ...

    @abstractmethod
    def list_employees(self) -> list[EmployeeRecord]: ...

    @abstractmethod
    def register_vacation(self, employee_id: str, start: date, end: date, days: int) -> str:
        pass

    @abstractmethod
    def register_advance(self, employee_id: str, amount: int) -> str:
        pass


class DocumentWorkflow(ABC):
    @abstractmethod
    def create_document(self, doc_type: str, author_id: str, title: str, payload: dict) -> DocumentRef: ...

    @abstractmethod
    def get_document(self, doc_id: str) -> DocumentRef: ...

    @abstractmethod
    def list_documents(self) -> list[DocumentRef]: ...
