import os
import tempfile
from datetime import date

os.environ["STORAGE"] = "memory"
os.environ["DIGITAL_HR_DB"] = os.path.join(tempfile.mkdtemp(prefix="janamen-tests-"), "never-used.db")

import pytest

from app.container import Container
from app.core.config import Settings

TODAY = date(2026, 10, 17)
PASSWORD = "Passw0rd!"


@pytest.fixture(params=["memory", "sqlite"])
def storage(request) -> str:
    return request.param


@pytest.fixture
def settings(storage, tmp_path) -> Settings:
    s = Settings()
    s.storage = storage
    s.db_path = tmp_path / "digital_hr_test.db"
    s.integration_mode = "mock"
    s.ai_mode = "off"
    return s


@pytest.fixture
def container(settings) -> Container:
    return Container(settings, today=lambda: TODAY)


@pytest.fixture
def client(settings, container):
    from fastapi.testclient import TestClient

    from app.main import create_app
    return TestClient(create_app(settings, container))


@pytest.fixture
def login(client):
    def _login(email: str) -> dict:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _login
