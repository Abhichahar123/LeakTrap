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

pytestmark = pytest.mark.integration

NOTICE = "We may share your data with partners.\nLast updated 2026-01-15."


@pytest.fixture
def client(session: Session):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    yield TestClient(app, client=("127.0.0.1", 50000))
    app.dependency_overrides.clear()


@pytest.fixture
def data(session: Session) -> dict:
    alice, bob = User(), User()
    session.add_all([alice, bob])
    session.flush()
    shop = Signup(site_name="Example Shop", site_domain="shop.example.com", alias="ab12@leaktrap.xyz",
                  nickname="Ocelot")
    news = Signup(site_name="Daily News")
    alice_bank = Signup(user_id=alice.id, site_name="Alice Bank", site_domain="bank.example",
                        alias="ef56@leaktrap.xyz", nickname="Kestrel")
    bob_forum = Signup(user_id=bob.id, site_name="Bob Forum")
    session.add_all([shop, news, alice_bank, bob_forum])
    session.commit()
    return {"alice": alice.id, "bob": bob.id, "shop": shop.id, "news": news.id,
            "alice_bank": alice_bank.id, "bob_forum": bob_forum.id}


def create(client, body, user_id=None):
    params = {"user_id": user_id} if user_id else {}
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
    assert stored.user_id is None  # owner copied from the signup
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
                        "source_url": "https://bank.example/privacy"}, user_id=data["alice"]).json()
    session.expire_all()
    assert session.get(ConsentReceipt, r["id"]).user_id == data["alice"]


@pytest.mark.parametrize(
    ("signup_key", "scope_key"),
    [("alice_bank", None), ("alice_bank", "bob"), ("bob_forum", "alice"), ("shop", "alice"), ("missing", None)],
)
def test_cannot_attach_to_signup_outside_scope(client, session, data, signup_key, scope_key) -> None:
    signup_id = data.get(signup_key, 987654321)
    before = receipt_count(session)
    response = create(client, {"signup_id": signup_id, "action": "accepted",
                               "source_url": "https://x.example/p"},
                      user_id=data[scope_key] if scope_key else None)
    assert response.status_code == 404
    assert response.json() == {"detail": "Signup not found in this scope"}
    assert receipt_count(session) == before


def test_unknown_scope_user_is_422(client, data) -> None:
    response = create(client, {"signup_id": data["shop"], "action": "accepted",
                               "source_url": "https://x.example/p"}, user_id=987654321)
    assert response.status_code == 422


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
    assert client.get("/consent-receipts", params={"signup_id": data["alice_bank"]}).status_code == 404


def test_empty_list(client, data) -> None:
    page = client.get("/consent-receipts").json()
    assert (page["items"], page["total"]) == ([], 0)


def test_unknown_and_out_of_scope_receipts_are_404(client, data) -> None:
    alice_receipt = create(client, {"signup_id": data["alice_bank"], "action": "accepted",
                                    "source_url": "https://bank.example/p"}, user_id=data["alice"]).json()["id"]
    assert client.get("/consent-receipts/987654321").status_code == 404
    assert client.get(f"/consent-receipts/{alice_receipt}").status_code == 404
    assert client.get(f"/consent-receipts/{alice_receipt}", params={"user_id": data["bob"]}).status_code == 404
    assert client.get(f"/consent-receipts/{alice_receipt}", params={"user_id": data["alice"]}).status_code == 200


def test_scopes_do_not_leak(client, data) -> None:
    create(client, {"signup_id": data["alice_bank"], "action": "accepted",
                    "source_url": "https://bank.example/p"}, user_id=data["alice"])
    create(client, {"signup_id": data["shop"], "action": "accepted", "source_url": "https://shop.example.com/p"})
    unowned = client.get("/consent-receipts").text
    alice = client.get("/consent-receipts", params={"user_id": data["alice"]}).text
    bob = client.get("/consent-receipts", params={"user_id": data["bob"]}).json()
    assert "Alice Bank" not in unowned and "Example Shop" in unowned
    assert "Alice Bank" in alice and "Example Shop" not in alice
    assert bob["total"] == 0


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
    session.add(ConsentReceipt(signup_id=data["shop"], privacy_notice_text="Old notice"))
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
    assert 1 <= len(statements) <= 2, statements
