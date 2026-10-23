"""Consent receipts against a live PostgreSQL test database (TEST_DATABASE_URL).
Every test runs in a transaction that is rolled back afterwards."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.main import app
from backend.models import ConsentReceipt, Signup, User
from backend.routes.dashboard import DashboardConfig, get_dashboard_config
from backend.schemas.consent_receipt import sha256_of
from tests.auth_support import make_account, sign_in

pytestmark = pytest.mark.integration

NOTICE = "We may share your data with partners.\nLast updated 2026-01-15."


@pytest.fixture
def accounts(session: Session) -> dict:
    return {"alice": make_account(session, "alice@example.com"), "bob": make_account(session, "bob@example.com")}


def local_client(session: Session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def client(session: Session, accounts):
    """Signed in as Alice."""
    client = local_client(session)
    sign_in(client, session, accounts["alice"])
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def bob_client(session: Session, accounts, client):
    bob = local_client(session)
    sign_in(bob, session, accounts["bob"])
    return bob


@pytest.fixture
def data(session: Session, accounts) -> dict:
    alice, bob = accounts["alice"].id, accounts["bob"].id
    shop = Signup(user_id=alice, site_name="Example Shop", site_domain="shop.example.com", alias="ab12@leaktrap.xyz",
                  nickname="Ocelot")
    news = Signup(user_id=alice, site_name="Daily News")
    alice_bank = Signup(user_id=alice, site_name="Alice Bank", site_domain="bank.example",
                        alias="ef56@leaktrap.xyz", nickname="Kestrel")
    bob_forum = Signup(user_id=bob, site_name="Bob Forum")
    historical = Signup(site_name="Historical Forum", alias="hist@leaktrap.xyz")
    session.add_all([shop, news, alice_bank, bob_forum, historical])
    session.commit()
    return {"alice": alice, "bob": bob, "shop": shop.id, "news": news.id,
            "alice_bank": alice_bank.id, "bob_forum": bob_forum.id, "historical": historical.id}


def create(client, body, **params):
    return client.post("/consent-receipts", json=body, params=params)


def receipt_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ConsentReceipt))


def test_create_full_receipt(client, session, data) -> None:
    occurred = "2026-10-01T09:30:00+00:00"
    response = create(client, {
        "signup_id": data["shop"], "action": "accepted",
        "source_url": "https://shop.example.com/privacy", "notice_version": " 2026-01-15 ",
        "notice_text": NOTICE, "consent_text": "I agree to marketing emails",
        "reported_occurred_at": occurred,
    })
    assert response.status_code == 201, response.text
    r = response.json()
    assert (r["site_name"], r["site_domain"]) == ("Example Shop", "shop.example.com")
    assert (r["action"], r["capture_source"], r["evidence_basis"]) == ("accepted", "manual", "user_reported")
    assert r["content_hash"] == sha256_of(NOTICE)
    assert r["notice_text"] == NOTICE and r["notice_text_stored"] is True
    assert r["notice_version"] == "2026-01-15"
    assert datetime.fromisoformat(r["reported_occurred_at"]) == datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    assert "does not prove" in r["legal_notice"]
    assert "recorded_at is when LeakTrace saved" in r["timestamp_note"]

    session.expire_all()
    stored = session.get(ConsentReceipt, r["id"])
    assert stored.user_id == data["alice"]  # owner copied from the signup
    assert stored.capture_source == "manual"
    assert stored.created_at.tzinfo is not None


def test_hash_only_receipt_stores_no_text(client, session, data) -> None:
    r = create(client, {"signup_id": data["news"], "action": "notice_only",
                        "content_hash": sha256_of(NOTICE)}).json()
    assert (r["notice_text_stored"], r["notice_text"], r["consent_text"]) == (False, None, None)
    assert r["reported_occurred_at"] is None  # not reported, not invented
    session.expire_all()
    assert session.get(ConsentReceipt, r["id"]).privacy_notice_text == ""


def test_owner_is_taken_from_signup(client, session, data) -> None:
    r = create(client, {"signup_id": data["alice_bank"], "action": "declined",
                        "source_url": "https://bank.example/privacy"}).json()
    session.expire_all()
    assert session.get(ConsentReceipt, r["id"]).user_id == data["alice"]


@pytest.mark.parametrize("signup_key", ["bob_forum", "historical", "missing"])
def test_cannot_attach_to_another_users_or_unowned_signup(client, session, data, signup_key) -> None:
    before = receipt_count(session)
    response = create(client, {"signup_id": data.get(signup_key, 987654321), "action": "accepted",
                               "source_url": "https://x.example/p"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Signup not found"}
    assert receipt_count(session) == before


def test_user_id_cannot_be_chosen_by_the_client(client, session, data) -> None:
    before = receipt_count(session)
    body = {"signup_id": data["bob_forum"], "action": "accepted", "source_url": "https://x.example/p"}
    assert create(client, body, user_id=data["bob"]).status_code == 404  # query parameter ignored
    assert create(client, {**body, "user_id": data["bob"]}).status_code == 422  # body field rejected
    assert receipt_count(session) == before


def test_list_pagination_and_retrieval(client, data) -> None:
    ids = [create(client, {"signup_id": data["shop"], "action": a, "source_url": "https://shop.example.com/p"}).json()["id"]
           for a in ("accepted", "declined", "notice_only")]
    page = client.get("/consent-receipts").json()
    assert page["total"] == 3
    assert [r["id"] for r in page["items"]] == ids[::-1]  # newest first
    assert "does not prove" in page["legal_notice"]
    second = client.get("/consent-receipts", params={"limit": 2, "offset": 2}).json()
    assert [r["id"] for r in second["items"]] == [ids[0]]
    assert "notice_text" not in page["items"][0] and "consent_text" not in page["items"][0]

    detail = client.get(f"/consent-receipts/{ids[1]}").json()
    assert detail["action"] == "declined"


def test_filter_by_signup(client, data) -> None:
    create(client, {"signup_id": data["shop"], "action": "accepted", "source_url": "https://a.example/p"})
    create(client, {"signup_id": data["news"], "action": "accepted", "source_url": "https://b.example/p"})
    page = client.get("/consent-receipts", params={"signup_id": data["news"]}).json()
    assert [r["site_name"] for r in page["items"]] == ["Daily News"]
    assert client.get("/consent-receipts", params={"signup_id": data["alice_bank"]}).json()["items"] == []
    for other in ("bob_forum", "historical"):  # not Alice's: indistinguishable from nonexistent
        assert client.get("/consent-receipts", params={"signup_id": data[other]}).status_code == 404


def test_empty_list(client, data) -> None:
    page = client.get("/consent-receipts").json()
    assert (page["items"], page["total"]) == ([], 0)


def test_other_users_receipts_are_404(client, bob_client, data) -> None:
    bob_receipt = create(bob_client, {"signup_id": data["bob_forum"], "action": "accepted",
                                      "source_url": "https://bob.example/p"}).json()["id"]
    assert client.get("/consent-receipts/987654321").status_code == 404
    assert client.get(f"/consent-receipts/{bob_receipt}").status_code == 404
    assert client.get(f"/consent-receipts/{bob_receipt}", params={"user_id": data["bob"]}).status_code == 404
    assert bob_client.get(f"/consent-receipts/{bob_receipt}").status_code == 200
    assert client.get("/consent-receipts", params={"signup_id": data["bob_forum"]}).status_code == 404


def test_lists_do_not_leak_between_users(client, bob_client, data) -> None:
    create(bob_client, {"signup_id": data["bob_forum"], "action": "accepted", "source_url": "https://bob.example/p"})
    create(client, {"signup_id": data["shop"], "action": "accepted", "source_url": "https://shop.example.com/p"})
    alice = client.get("/consent-receipts").text
    bob = bob_client.get("/consent-receipts").json()
    assert "Bob Forum" not in alice and "Example Shop" in alice
    assert [r["site_name"] for r in bob["items"]] == ["Bob Forum"]


def test_responses_exclude_unrelated_signup_fields(client, data) -> None:
    r = create(client, {"signup_id": data["shop"], "action": "accepted", "source_url": "https://shop.example.com/p"})
    texts = r.text + client.get("/consent-receipts").text + client.get(f"/consent-receipts/{r.json()['id']}").text
    for value in ("ab12@leaktrap.xyz", "Ocelot", "Kestrel", "ef56@leaktrap.xyz", '"alias"', '"nickname"', '"user_id"'):
        assert value not in texts, value


def test_untrusted_text_is_returned_as_plain_data(client, data) -> None:
    hostile = '<script>alert("x")</script><img src=x onerror=alert(1)>'
    r = create(client, {"signup_id": data["shop"], "action": "notice_only", "notice_text": hostile,
                        "consent_text": hostile}).json()
    detail = client.get(f"/consent-receipts/{r['id']}")
    assert detail.headers["content-type"].startswith("application/json")
    assert detail.json()["notice_text"] == hostile  # stored verbatim, rendered as text by the dashboard


def test_legacy_receipts_are_labelled_unknown_not_verified(client, session, data) -> None:
    session.add(ConsentReceipt(user_id=data["alice"], signup_id=data["shop"], privacy_notice_text="Old notice"))
    session.commit()
    [legacy] = client.get("/consent-receipts").json()["items"]
    assert (legacy["action"], legacy["capture_source"], legacy["evidence_basis"]) == (None, None, "unknown")
    assert legacy["notice_text_stored"] is True


def test_receipt_survives_signup_deletion(client, session, data) -> None:
    r = create(client, {"signup_id": data["news"], "action": "accepted", "source_url": "https://n.example/p"}).json()
    assert client.delete(f"/signups/{data['news']}").status_code == 204
    kept = client.get(f"/consent-receipts/{r['id']}").json()
    assert (kept["signup_id"], kept["site_name"], kept["action"]) == (None, None, "accepted")


@pytest.mark.parametrize(("column", "value"), [("action", "verified"), ("capture_source", "verified")])
def test_database_rejects_unsupported_status_values(session, data, column, value) -> None:
    session.add(ConsentReceipt(signup_id=data["shop"], privacy_notice_text="x", **{column: value}))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_list_uses_bounded_queries(client, session, data) -> None:
    from sqlalchemy import event

    for _ in range(5):
        create(client, {"signup_id": data["shop"], "action": "accepted", "source_url": "https://s.example/p"})
    statements = []
    engine = session.get_bind()
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert client.get("/consent-receipts", params={"limit": 100}).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert 1 <= len(statements) <= 4, statements  # session + user lookup, count, page
