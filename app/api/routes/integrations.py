from fastapi import APIRouter, Depends

from app.api.deps import get_container, require_roles
from app.container import Container
from app.integrations.base import DocumentRef, EmployeeRecord
from app.models.domain import Role, User

router = APIRouter(prefix="/mock", tags=["Заглушки интеграций (1С:ЗУП, Documentolog)"])
HR = require_roles(Role.HR)


@router.get("/1c-zup/employees", response_model=list[EmployeeRecord], summary="1С:ЗУП: список сотрудников")
def zup_employees(_: User = Depends(HR), c: Container = Depends(get_container)):
    return c.personnel.list_employees()


@router.get("/1c-zup/employees/{employee_id}", response_model=EmployeeRecord, summary="1С:ЗУП: карточка сотрудника")
def zup_employee(employee_id: str, _: User = Depends(HR), c: Container = Depends(get_container)):
    return c.personnel.get_employee(employee_id)


@router.get("/1c-zup/registered-documents", summary="Журнал документов, отправленных в ЗУП (только mock)")
def zup_journal(_: User = Depends(HR), c: Container = Depends(get_container)):
    return getattr(c.personnel, "registered", [])


@router.get("/documentolog/documents", response_model=list[DocumentRef], summary="Documentolog: список документов")
def dl_documents(_: User = Depends(HR), c: Container = Depends(get_container)):
    return c.docflow.list_documents()


@router.get("/documentolog/documents/{doc_id}", response_model=DocumentRef, summary="Documentolog: документ по id")
def dl_document(doc_id: str, _: User = Depends(HR), c: Container = Depends(get_container)):
    return c.docflow.get_document(doc_id)
