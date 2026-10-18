from __future__ import annotations

from app.core.config import Settings
from app.integrations.base import DocumentWorkflow, PersonnelSystem
from app.integrations.mock_documentolog import MockDocumentologClient
from app.integrations.mock_zup import MockZupClient
from app.integrations.real_clients import DocumentologHttpClient, ZupHttpClient
from app.repositories.memory import UserRepository


def build_personnel_system(settings: Settings, users: UserRepository) -> PersonnelSystem:
    if settings.integration_mode == "real":
        return ZupHttpClient(settings.zup_base_url)
    return MockZupClient(users)


def build_document_workflow(settings: Settings) -> DocumentWorkflow:
    if settings.integration_mode == "real":
        return DocumentologHttpClient(settings.documentolog_base_url)
    return MockDocumentologClient()
