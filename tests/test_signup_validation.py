"""Request validation for the signup API. No database is needed: validation
fails before the handler runs, and get_db is replaced with a dummy."""

import pytest
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.main import app
from backend.schemas.signup import SignupCreate


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client: TestClient, body: dict):
    return client.post("/signups", json=body)


@pytest.mark.parametrize("site_name", ["", "   ", "!!!", "a\nb", "x" * 256, 123, None])
def test_invalid_site_name_rejected(client, site_name) -> None:
    assert post(client, {"site_name": site_name}).status_code == 422


def test_site_name_whitespace_is_collapsed() -> None:
    assert SignupCreate(site_name="  Example   Shop ").site_name == "Example Shop"


@pytest.mark.parametrize(
    "domain", ["", "example", "https://example.com", "example.com/x", "127.0.0.1", "a..com"]
)
def test_invalid_site_domain_rejected(client, domain) -> None:
    assert post(client, {"site_name": "Shop", "site_domain": domain}).status_code == 422


def test_site_domain_is_normalized() -> None:
    assert SignupCreate(site_name="Shop", site_domain=" Shop.Example.COM. ").site_domain == (
        "shop.example.com"
    )


@pytest.mark.parametrize("surname", ["", "   ", "Smith2", "Smith!", "a" * 101, "O''Brien"])
def test_invalid_surname_variant_rejected(client, surname) -> None:
    assert post(client, {"site_name": "Shop", "surname_variant": surname}).status_code == 422


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  van   der  Berg ", "van der Berg"), ("O'Brien-Smythe", "O'Brien-Smythe"),
     ("Müller", "Müller")],
)
def test_surname_variant_normalized_preserving_case(raw: str, expected: str) -> None:
    assert SignupCreate(site_name="Shop", surname_variant=raw).surname_variant == expected


@pytest.mark.parametrize(
    "field", [{"id": 5}, {"alias": "x@example.com"}, {"nickname": "Falcon"},
              {"created_at": "2026-01-01T00:00:00Z"}, {"real_name_used": True},
              {"real_name": "Jane Doe"}],
)
def test_server_generated_and_unknown_fields_rejected(client, field) -> None:
    assert post(client, {"site_name": "Shop", **field}).status_code == 422


@pytest.mark.parametrize("user_id", [0, -1, 2**63, "abc"])
def test_invalid_user_id_rejected(client, user_id) -> None:
    assert post(client, {"site_name": "Shop", "user_id": user_id}).status_code == 422


def test_nickname_generation_defaults_follow_real_name_required() -> None:
    assert SignupCreate(site_name="Shop").generate_nickname is True
    assert SignupCreate(site_name="Shop", real_name_required=True).generate_nickname is False
    explicit = SignupCreate(site_name="Shop", real_name_required=True, generate_nickname=True)
    assert explicit.generate_nickname is True


@pytest.mark.parametrize(
    "path", ["/signups/0", "/signups/-1", "/signups/abc", f"/signups/{2**63}"]
)
def test_invalid_signup_id_rejected(client, path) -> None:
    assert client.get(path).status_code == 422
    assert client.delete(path).status_code == 422


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "limit=abc", "site_domain=http://x.com"]
)
def test_invalid_list_parameters_rejected(client, query) -> None:
    assert client.get(f"/signups?{query}").status_code == 422
