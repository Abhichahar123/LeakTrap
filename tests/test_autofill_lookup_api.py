"""Autofill alias recall against the isolated PostgreSQL test database.

Alice is signed in. Bob has a signup for the same site, and there is an
unowned historical signup too: neither may ever be returned to Alice.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.main import app
from backend.models import Signup
from backend.routes.dashboard import DashboardConfig, get_dashboard_config
from tests.auth_support import ORIGIN, extension_token, make_account, sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def accounts(session: Session) -> dict:
    return {"alice": make_account(session, "alice@example.com"), "bob": make_account(session, "bob@example.com")}


@pytest.fixture
def client(session: Session, accounts):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    client = TestClient(app, client=("127.0.0.1", 50000))
    sign_in(client, session, accounts["alice"])
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def data(session: Session, accounts) -> dict:
    alice, bob = accounts["alice"].id, accounts["bob"].id
    rows = {
        "shop_old": Signup(user_id=alice, site_name="Shop", site_domain="shop.example.com", alias="aa11@leaktrap.xyz", nickname="Ocelot"),
        "shop_new": Signup(user_id=alice, site_name="Shop again", site_domain="shop.example.com", alias="bb22@leaktrap.xyz"),
        "parent": Signup(user_id=alice, site_name="Example", site_domain="example.com", alias="cc33@leaktrap.xyz"),
        "login_sub": Signup(user_id=alice, site_name="Shop login", site_domain="login.shop.example.com", alias="dd44@leaktrap.xyz"),
        "www": Signup(user_id=alice, site_name="WWW", site_domain="www.other.example", alias="ee55@leaktrap.xyz"),
        "bob_shop": Signup(user_id=bob, site_name="Bob Shop", site_domain="shop.example.com", alias="ff66@leaktrap.xyz"),
        "unowned_shop": Signup(site_name="Historical Shop", site_domain="shop.example.com", alias="gg77@leaktrap.xyz"),
    }
    session.add_all(rows.values())
    session.commit()
    return {k: v.id for k, v in rows.items()}


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


def test_other_users_and_unowned_signups_are_never_returned(client, session, data, accounts) -> None:
    text = str(lookup(client, "shop.example.com"))
    for leaked in ("Bob Shop", "ff66", "Historical Shop", "gg77"):
        assert leaked not in text
    # A user_id parameter has no effect: scope always comes from the session.
    assert lookup(client, "shop.example.com", user_id=accounts["bob"].id) == lookup(client, "shop.example.com")
    bob = TestClient(app, client=("127.0.0.1", 50000))
    sign_in(bob, session, accounts["bob"])
    assert [i["site_name"] for i in lookup(bob, "shop.example.com")["items"]] == ["Bob Shop"]


def test_extension_token_with_lookup_scope(session, data, accounts) -> None:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    try:
        ext = TestClient(app, client=("127.0.0.1", 50000))
        token = extension_token(session, accounts["alice"], scopes={"signups:lookup"})
        ok = ext.post("/autofill/lookup", json={"site_domain": "shop.example.com"}, headers={"Authorization": f"Bearer {token}"})
        assert [i["id"] for i in ok.json()["items"]] == [data["shop_new"], data["shop_old"]]
        no_scope = extension_token(session, accounts["alice"], scopes={"receipts:create"})
        denied = ext.post("/autofill/lookup", json={"site_domain": "shop.example.com"}, headers={"Authorization": f"Bearer {no_scope}"})
        assert denied.status_code == 403
        assert ext.post("/autofill/lookup", json={"site_domain": "shop.example.com"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_signed_out_lookup_is_refused(session, data) -> None:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    try:
        anon = TestClient(app, client=("127.0.0.1", 50000), headers={"Origin": ORIGIN})
        assert anon.post("/autofill/lookup", json={"site_domain": "shop.example.com"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_lookup_never_creates_signups(client, session, data) -> None:
    before = session.scalar(select(func.count()).select_from(Signup))
    assert lookup(client, "brand-new.example")["items"] == []
    assert session.scalar(select(func.count()).select_from(Signup)) == before


def test_response_has_only_recall_fields(client, data) -> None:
    item = lookup(client, "shop.example.com")["items"][0]
    assert set(item) == {"id", "site_name", "site_domain", "alias", "nickname", "real_name_required", "created_at"}
