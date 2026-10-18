from datetime import date

import pytest

from app.core.errors import IntegrationError, NotFoundError
from app.integrations.factory import build_document_workflow, build_personnel_system
from app.integrations.mock_documentolog import MockDocumentologClient
from app.integrations.mock_zup import MockZupClient
from app.integrations.real_clients import DocumentologHttpClient, ZupHttpClient

D1, D2 = date(2026, 11, 2), date(2026, 11, 6)


def test_zup_get_and_list(container):
    rec = container.personnel.get_employee("u-3")
    assert rec.personnel_number == "00103" and rec.manager_id == "u-2" and rec.vacation_days_left == 21
    assert len(container.personnel.list_employees()) == 6


def test_zup_unknown_employee(container):
    with pytest.raises(NotFoundError):
        container.personnel.get_employee("u-999")
    with pytest.raises(NotFoundError):
        container.personnel.register_vacation("u-999", D1, D2, 5)


def test_zup_register_vacation_reduces_balance_and_journals(container):
    doc_id = container.personnel.register_vacation("u-3", D1, D2, 5)
    assert doc_id.startswith("ZUP-VAC-")
    assert container.users.get("u-3").vacation_days_left == 16
    assert container.personnel.registered[-1] == {
        "id": doc_id, "type": "vacation", "employee_id": "u-3", "start": "2026-11-02", "end": "2026-11-06", "days": 5}


def test_zup_rejects_vacation_over_balance(container):
    with pytest.raises(IntegrationError):
        container.personnel.register_vacation("u-3", D1, D2, 100)
    assert container.users.get("u-3").vacation_days_left == 21


def test_zup_register_advance(container):
    doc_id = container.personnel.register_advance("u-3", 50000)
    assert doc_id.startswith("ZUP-ADV-") and container.personnel.registered[-1]["amount"] == 50000


def test_documentolog_create_get_list():
    dl = MockDocumentologClient()
    a = dl.create_document("vacation_order", "u-3", "Приказ", {"days": 5})
    b = dl.create_document("advance_application", "u-4", "Заявление", {"amount": 1})
    assert a.id != b.id and a.status == "registered" and a.id in a.url
    assert dl.get_document(a.id) == a
    assert {d.id for d in dl.list_documents()} == {a.id, b.id}
    with pytest.raises(NotFoundError):
        dl.get_document("DL-404")


def test_factory_mock_and_real_modes(settings, container):
    assert isinstance(build_personnel_system(settings, container.users), MockZupClient)
    assert isinstance(build_document_workflow(settings), MockDocumentologClient)
    settings.integration_mode = "real"
    assert isinstance(build_personnel_system(settings, container.users), ZupHttpClient)
    assert isinstance(build_document_workflow(settings), DocumentologHttpClient)


@pytest.mark.parametrize("call", [
    lambda z, d: z.get_employee("u-1"),
    lambda z, d: z.list_employees(),
    lambda z, d: z.register_vacation("u-1", D1, D2, 5),
    lambda z, d: z.register_advance("u-1", 1),
    lambda z, d: d.create_document("t", "u-1", "x", {}),
    lambda z, d: d.get_document("DL-1"),
    lambda z, d: d.list_documents(),
])
def test_real_clients_are_explicit_stubs(call):
    with pytest.raises(NotImplementedError):
        call(ZupHttpClient("http://zup"), DocumentologHttpClient("http://dl"))
