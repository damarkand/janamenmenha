from __future__ import annotations

from itertools import count
from threading import RLock

from app.core.errors import NotFoundError
from app.integrations.base import DocumentRef, DocumentWorkflow


class MockDocumentologClient(DocumentWorkflow):
    def __init__(self):
        self._docs: dict[str, DocumentRef] = {}
        self._payloads: dict[str, dict] = {}
        self._seq = count(1)
        self._lock = RLock()

    def create_document(self, doc_type: str, author_id: str, title: str, payload: dict) -> DocumentRef:
        with self._lock:
            doc_id = f"DL-{next(self._seq):06d}"
            doc = DocumentRef(id=doc_id, doc_type=doc_type, title=title, status="registered",
                              url=f"https://documentolog.example/docs/{doc_id}")
            self._docs[doc_id] = doc
            self._payloads[doc_id] = {"author_id": author_id, **payload}
        return doc

    def get_document(self, doc_id: str) -> DocumentRef:
        doc = self._docs.get(doc_id)
        if not doc:
            raise NotFoundError(f"Documentolog: документ {doc_id} не найден")
        return doc

    def list_documents(self) -> list[DocumentRef]:
        return list(self._docs.values())
