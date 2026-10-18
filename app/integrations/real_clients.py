from __future__ import annotations

from datetime import date

from app.integrations.base import DocumentRef, DocumentWorkflow, EmployeeRecord, PersonnelSystem


class ZupHttpClient(PersonnelSystem):
    def __init__(self, base_url: str):
        self.base_url = base_url

    def get_employee(self, employee_id: str) -> EmployeeRecord:
        raise NotImplementedError("TODO: получить сотрудника из 1С:ЗУП и смаппить в EmployeeRecord")

    def list_employees(self) -> list[EmployeeRecord]:
        raise NotImplementedError("TODO: получить список сотрудников из 1С:ЗУП")

    def register_vacation(self, employee_id: str, start: date, end: date, days: int) -> str:
        raise NotImplementedError("TODO: создать документ «Отпуск» в 1С:ЗУП")

    def register_advance(self, employee_id: str, amount: int) -> str:
        raise NotImplementedError("TODO: создать документ на аванс в 1С:ЗУП")


class DocumentologHttpClient(DocumentWorkflow):
    def __init__(self, base_url: str):
        self.base_url = base_url

    def create_document(self, doc_type: str, author_id: str, title: str, payload: dict) -> DocumentRef:
        raise NotImplementedError("TODO: создать документ в Documentolog")

    def get_document(self, doc_id: str) -> DocumentRef:
        raise NotImplementedError("TODO: получить статус документа из Documentolog")

    def list_documents(self) -> list[DocumentRef]:
        raise NotImplementedError("TODO: получить список документов из Documentolog")
