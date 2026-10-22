"""Autofill alias recall against the isolated PostgreSQL test database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.main import app
from backend.models import Signup, User
from backend.routes.dashboard import DashboardConfig, get_dashboard_config

pytestmark = pytest.mark.integration


@pytest.fixture
def client(session: Session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    yield TestClient(app, client=("127.0.0.1", 50000))
    app.dependency_overrides.clear()


@pytest.fixture
def data(session: Session) -> dict:
    alice = User()
    session.add(alice)
    session.flush()
    rows = {
        "shop_old": Signup(site_name="Shop", site_domain="shop.example.com", alias="aa11@leaktrap.xyz", nickname="Ocelot"),
        "shop_new": Signup(site_name="Shop again", site_domain="shop.example.com", alias="bb22@leaktrap.xyz"),
        "parent": Signup(site_name="Example", site_domain="example.com", alias="cc33@leaktrap.xyz"),
        "login_sub": Signup(site_name="Shop login", site_domain="login.shop.example.com", alias="dd44@leaktrap.xyz"),
        "www": Signup(site_name="WWW", site_domain="www.other.example", alias="ee55@leaktrap.xyz"),
        "alice_shop": Signup(user_id=alice.id, site_name="Alice Shop", site_domain="shop.example.com", alias="ff66@leaktrap.xyz"),
    }
    session.add_all(rows.values())
    session.commit()
    return {"alice": alice.id, **{k: v.id for k, v in rows.items()}}


def lookup(client, domain, **params):
    response = client.post("/autofill/lookup", params=params, json={"site_domain": domain})
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_domain_newest_first(client, data) -> None:
    body = lookup(client, "Shop.Example.COM")
    assert body["site_domain"] == "shop.example.com"
    assert [i["id"] for i in body["items"]] == [data["shop_new"], data["shop_old"]]
    assert body["items"][1] == {**body["items"][1], "alias": "aa11@leaktrap.xyz", "nickname": "Ocelot",
                                "real_name_required": False}
    assert "Exact domain match only" in body["note"]


def test_no_parent_or_sibling_subdomain_reuse(client, data) -> None:
    assert [i["id"] for i in lookup(client, "example.com")["items"]] == [data["parent"]]
    assert [i["id"] for i in lookup(client, "login.shop.example.com")["items"]] == [data["login_sub"]]
    assert lookup(client, "checkout.shop.example.com")["items"] == []
    assert lookup(client, "other.example")["items"] == []  # www.other.example is a different exact domain


def test_scope_isolation(client, data) -> None:
    unowned = lookup(client, "shop.example.com")
    assert "Alice Shop" not in str(unowned) and "ff66" not in str(unowned)
    alice = lookup(client, "shop.example.com", user_id=data["alice"])
    assert [i["site_name"] for i in alice["items"]] == ["Alice Shop"]
    assert client.post("/autofill/lookup", params={"user_id": 987654321}, json={"site_domain": "shop.example.com"}).status_code == 422


def test_lookup_never_creates_signups(client, session, data) -> None:
    before = session.scalar(select(func.count()).select_from(Signup))
    assert lookup(client, "brand-new.example")["items"] == []
    assert session.scalar(select(func.count()).select_from(Signup)) == before


def test_response_has_only_recall_fields(client, data) -> None:
    item = lookup(client, "shop.example.com")["items"][0]
    assert set(item) == {"id", "site_name", "site_domain", "alias", "nickname", "real_name_required", "created_at"}
