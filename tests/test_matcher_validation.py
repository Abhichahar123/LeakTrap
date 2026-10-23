"""Matcher request validation and error handling without a database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.database import get_db
from backend.main import app
from tests.auth_support import FAKE_HEADERS, fake_auth


class BrokenSession:
    """Raises the error a dropped database connection would raise."""

    def get(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    scalars = get


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    fake_auth(app)
    yield TestClient(app, headers=FAKE_HEADERS)
    app.dependency_overrides.clear()


def post(client, body):
    return client.post("/matcher/check", json=body)


@pytest.mark.parametrize(
    "address",
    ["", "   ", "not-an-email", "a@b", "Name <a@shop.example.com>", "a@@shop.example.com",
     "a@shop.example.com,b@shop.example.com", "a@https://shop.example.com", ".a@shop.example.com",
     "a@127.0.0.1", 42],
)
@pytest.mark.parametrize("field", ["recipient", "sender"])
def test_malformed_addresses_rejected(client, field, address) -> None:
    response = post(client, {field: address})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == field


def test_request_without_any_clue_rejected(client) -> None:
    assert post(client, {}).status_code == 422
    assert post(client, {"subject": "Hi Ocelot"}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [{"recipient": "a@leaktrap.xyz", "body": "full message"},
     {"recipient": "a@leaktrap.xyz", "subject": "x" * 999},
     {"nickname": "   "},
     {"surname_variant": "x" * 101},
     {"recipient": "a@leaktrap.xyz", "user_id": 0}, {"recipient": "a@leaktrap.xyz", "user_id": 2},
     {"recipient": "a@leaktrap.xyz", "record_incident": "maybe"}],
)
def test_invalid_fields_rejected(client, body) -> None:
    assert post(client, body).status_code == 422


@pytest.mark.parametrize(
    "body", [{"recipient": "a@leaktrap.xyz"}, {"sender": "x@shop.example.com"}]
)
def test_database_error_returns_503_without_details(body) -> None:
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    fake_auth(app)
    try:
        response = TestClient(app, headers=FAKE_HEADERS).post("/matcher/check", json=body)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}


def test_endpoint_is_documented() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    operation = schema["paths"]["/matcher/check"]["post"]
    assert "never proof of a leak" in operation["description"]
