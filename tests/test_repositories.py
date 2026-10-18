import json

import pytest
from pydantic import BaseModel, ValidationError

from app.models.domain import RequestStatus, RequestType, Role
from app.repositories.memory import InMemoryRepository
from app.repositories.seed import load_seed


class Item(BaseModel):
    id: str
    value: int = 0


def test_next_id_skips_existing_ids():
    repo = InMemoryRepository("x", [Item(id="x-2")])
    assert repo.next_id() == "x-3"
    assert repo.next_id() == "x-4"


def test_add_get_list_save():
    repo = InMemoryRepository("x")
    item = repo.add(Item(id=repo.next_id(), value=1))
    assert repo.get(item.id) is item and repo.get("nope") is None
    item.value = 5
    repo.save(item)
    assert repo.list(lambda i: i.value == 5) == [item] and len(repo.list()) == 1


def test_user_repository(container):
    assert container.users.get_by_email("  HR@JanaMen.kz ").id == "u-1"
    assert container.users.get_by_email("nobody@janamen.kz") is None
    assert {u.id for u in container.users.direct_reports("u-2")} == {"u-3", "u-4"}
    assert {u.id for u in container.users.by_role(Role.MANAGER)} == {"u-2", "u-5"}


def test_request_repository_filters(container):
    repo = container.request_repo
    assert [r.id for r in repo.by_user("u-4", RequestType.ADVANCE, {RequestStatus.PENDING})] == ["req-2"]
    assert repo.by_user("u-4", RequestType.VACATION) == []
    assert [r.id for r in repo.for_users({"u-3"})] == ["req-1"]


def test_enrollment_and_notification_repositories(container):
    assert container.enrollment_repo.find("u-3", "c-2").id == "enr-2"
    assert container.enrollment_repo.find("u-3", "c-99") is None
    assert [n.id for n in container.notification_repo.by_user("u-3")] == ["n-2", "n-1"]


def test_seed_loads_everything_and_hashes_passwords(settings):
    seed = load_seed(settings.data_dir)
    assert {k: len(v) for k, v in seed.items()} == {
        "users": 6, "courses": 4, "enrollments": 4, "requests": 3, "notifications": 4}
    assert all(u.password_hash.startswith("pbkdf2_sha256$") for u in seed["users"])


def test_seed_missing_files_give_empty_lists(tmp_path):
    assert all(v == [] for v in load_seed(tmp_path).values())


def test_seed_invalid_data_fails_fast(tmp_path):
    (tmp_path / "users.json").write_text(json.dumps([{"id": "u-1", "password": "x", "role": "boss"}]))
    with pytest.raises(ValidationError):
        load_seed(tmp_path)
