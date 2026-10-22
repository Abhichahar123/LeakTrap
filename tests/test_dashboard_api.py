"""Dashboard API against a live PostgreSQL test database (TEST_DATABASE_URL).
Every test runs in a transaction that is rolled back afterwards."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.main import app
from backend.models import MailLog, Signup, User
from backend.routes.dashboard import DashboardConfig, get_dashboard_config
from backend.services import matcher

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SENSITIVE = ["ab12@leaktrap.xyz", "cd34@leaktrap.xyz", "ef56@leaktrap.xyz", "Ocelot", "Kestrel",
             "Dhingraa", "legacy@sender.example", "Secret subject", "f" * 64]


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
                  nickname="Ocelot", surname_variant="Dhingraa")
    news = Signup(site_name="Daily News", alias="cd34@leaktrap.xyz")
    bank = Signup(user_id=alice.id, site_name="Alice Bank", site_domain="bank.example",
                  alias="ef56@leaktrap.xyz", nickname="Kestrel")
    bob_site = Signup(user_id=bob.id, site_name="Bob Forum")
    session.add_all([shop, news, bank, bob_site])
    session.flush()
    session.add_all([
        # Pre-ingestion row: has full sender and subject, no status. Never shown.
        MailLog(signup_id=shop.id, alias="ab12@leaktrap.xyz", sender="legacy@sender.example",
                subject="Secret subject", received_at=T0),
        MailLog(signup_id=shop.id, alias="ab12@leaktrap.xyz", sender_domain="broker.example",
                match_status="matched", match_confidence="high", message_id_hash="f" * 64,
                received_at=T0 + timedelta(hours=1)),
        MailLog(signup_id=news.id, alias="cd34@leaktrap.xyz", sender_domain="shop.example.com",
                match_status="ambiguous", match_confidence="medium", received_at=T0 + timedelta(hours=2)),
        MailLog(alias="zz99@leaktrap.xyz", match_status="no_match", match_confidence="none",
                received_at=T0 + timedelta(hours=3)),
        MailLog(user_id=alice.id, signup_id=bank.id, alias="ef56@leaktrap.xyz",
                match_status="matched", match_confidence="high", received_at=T0),
        MailLog(user_id=bob.id, match_status="no_match", match_confidence="none", received_at=T0),
    ])
    session.commit()
    return {"alice": alice.id, "bob": bob.id, "shop": shop.id, "news": news.id, "bank": bank.id}


def get(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_dataset(client) -> None:
    overview = get(client, "/dashboard/api/overview")
    assert {k: overview[k] for k in ("signups_total", "emails_total", "matched", "ambiguous",
                                    "no_match", "unprocessed")} == dict.fromkeys(
        ("signups_total", "emails_total", "matched", "ambiguous", "no_match", "unprocessed"), 0)
    for path in ("/dashboard/api/signups", "/dashboard/api/emails"):
        page = get(client, path)
        assert (page["items"], page["total"]) == ([], 0)


def test_overview_counts_unowned_scope(client, data) -> None:
    o = get(client, "/dashboard/api/overview")
    assert (o["signups_total"], o["emails_total"]) == (2, 4)
    assert (o["matched"], o["ambiguous"], o["no_match"], o["unprocessed"]) == (1, 1, 1, 1)
    assert o["scope"]["user_id"] is None
    assert "not proof" in o["notice"]


def test_overview_counts_user_scope(client, data) -> None:
    o = get(client, "/dashboard/api/overview", user_id=data["alice"])
    assert (o["signups_total"], o["emails_total"], o["matched"]) == (1, 1, 1)
    assert o["scope"]["user_id"] == data["alice"]


def test_unknown_user_scope_is_422(client, data) -> None:
    assert client.get("/dashboard/api/overview", params={"user_id": 987654321}).status_code == 422


def test_signups_list_masks_markers_and_counts_emails(client, data) -> None:
    page = get(client, "/dashboard/api/signups")
    assert page["total"] == 2
    by_name = {s["site_name"]: s for s in page["items"]}
    shop = by_name["Example Shop"]
    assert shop["alias_masked"] == "•••@leaktrap.xyz"
    assert (shop["has_nickname"], shop["has_surname_variant"], shop["email_count"]) == (True, True, 2)
    assert by_name["Daily News"]["email_count"] == 1
    assert not {"alias", "nickname", "surname_variant", "user_id"} & set(shop)


def test_signups_pagination(client, data) -> None:
    all_ids = [s["id"] for s in get(client, "/dashboard/api/signups")["items"]]
    assert all_ids == [data["news"], data["shop"]]  # newest first (id breaks created_at ties)
    second = get(client, "/dashboard/api/signups", limit=1, offset=1)
    assert [s["id"] for s in second["items"]] == [data["shop"]]
    assert (second["limit"], second["offset"], second["total"]) == (1, 1, 2)
    assert get(client, "/dashboard/api/signups", offset=50)["items"] == []


def test_email_activity_newest_first_with_site(client, data) -> None:
    page = get(client, "/dashboard/api/emails")
    assert page["total"] == 4
    assert [m["match_status"] for m in page["items"]] == ["no_match", "ambiguous", "matched", None]
    unknown, ambiguous, matched, legacy = page["items"]
    assert (unknown["recipient_known"], unknown["site_name"]) == (False, None)
    assert (matched["site_name"], matched["site_domain"]) == ("Example Shop", "shop.example.com")
    assert matched["sender_domain"] == "broker.example"
    assert ambiguous["match_confidence"] == "medium"
    assert legacy["match_status"] is None and legacy["sender_domain"] is None


@pytest.mark.parametrize(
    ("status", "expected"), [("matched", 1), ("ambiguous", 1), ("no_match", 1), ("unprocessed", 1)]
)
def test_email_status_filter(client, data, status, expected) -> None:
    page = get(client, "/dashboard/api/emails", status=status)
    assert page["total"] == expected
    assert all(m["match_status"] == (None if status == "unprocessed" else status) for m in page["items"])


def test_email_pagination(client, data) -> None:
    page = get(client, "/dashboard/api/emails", limit=2, offset=2)
    assert [m["match_status"] for m in page["items"]] == ["matched", None]
    assert page["total"] == 4


def test_email_detail_uses_only_stored_data_and_matcher_limitations(client, data) -> None:
    matched_id = get(client, "/dashboard/api/emails", status="matched")["items"][0]["id"]
    detail = get(client, f"/dashboard/api/emails/{matched_id}")
    assert (detail["match_status"], detail["match_confidence"]) == ("matched", "high")
    assert detail["limitations"] == list(matcher.LIMITATIONS)
    assert "not proof" in detail["notice"]
    assert "Only the match status and confidence were stored" in detail["stored_details"]
    assert "signals" not in detail
    assert "confirmed" not in str(detail).lower()


def test_email_detail_outside_scope_is_404(client, data) -> None:
    alice_mail = get(client, "/dashboard/api/emails", user_id=data["alice"])["items"][0]["id"]
    assert client.get(f"/dashboard/api/emails/{alice_mail}").status_code == 404
    assert client.get(f"/dashboard/api/emails/{alice_mail}", params={"user_id": data["bob"]}).status_code == 404
    assert client.get("/dashboard/api/emails/987654321").status_code == 404


def test_scopes_do_not_leak_other_users(client, data) -> None:
    unowned = str([get(client, p) for p in ("/dashboard/api/signups", "/dashboard/api/emails")])
    assert "Alice Bank" not in unowned and "Bob Forum" not in unowned
    alice = str([get(client, p, user_id=data["alice"]) for p in ("/dashboard/api/signups", "/dashboard/api/emails")])
    assert "Alice Bank" in alice
    assert "Example Shop" not in alice and "Bob Forum" not in alice


def test_sensitive_fields_never_returned(client, data) -> None:
    texts = []
    for scope in ({}, {"user_id": data["alice"]}):
        for path in ("/dashboard/api/overview", "/dashboard/api/signups", "/dashboard/api/emails"):
            texts.append(client.get(path, params=scope).text)
        for item in get(client, "/dashboard/api/emails", **scope)["items"]:
            texts.append(client.get(f"/dashboard/api/emails/{item['id']}", params=scope).text)
    combined = "\n".join(texts)
    for value in SENSITIVE:
        assert value not in combined, value
    for key in ('"alias"', '"nickname"', '"sender"', '"subject"', '"message_id_hash"'):
        assert key not in combined, key


@pytest.mark.parametrize("path", ["/dashboard/api/signups", "/dashboard/api/emails"])
def test_list_query_count_does_not_grow_with_rows(client, session, data, path) -> None:
    statements = []
    engine = session.get_bind()
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        get(client, path, limit=100)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert 1 <= len(statements) <= 2, statements  # one count + one page query
