"""Signup API tests against a live PostgreSQL test database (TEST_DATABASE_URL).

Each test runs inside a transaction that is rolled back afterwards, except the
concurrency test, which commits real rows and deletes exactly those rows.
"""

import re
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import get_db
from backend.main import app
from backend.models import ConsentReceipt, MailLog, Signup, User
from backend.routes.signups import get_alias_config
from backend.services import alias_generator, nickname_generator, signup_service
from backend.services.alias_generator import AliasConfig
from backend.services.nickname_generator import NicknameExhaustedError
from tests.auth_support import ORIGIN, make_account, sign_in

pytestmark = pytest.mark.integration

ALIAS_CONFIG = AliasConfig(domain="aliases.test.example", prefix="lt", suffix_length=4)
ALIAS_PATTERN = r"lt\.[a-z0-9]{4}@aliases\.test\.example"


@pytest.fixture
def alice(session: Session) -> User:
    return make_account(session, "alice@example.com")


@pytest.fixture
def client(session: Session, alice: User):
    """Signed in as Alice."""
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_alias_config] = lambda: ALIAS_CONFIG
    client = TestClient(app)
    sign_in(client, session, alice)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def bob_client(session: Session, client):
    """A second, independent account (Bob), signed in on its own client."""
    bob = make_account(session, "bob@example.com")
    other = TestClient(app)
    sign_in(other, session, bob)
    return other


def signup_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Signup))


def make_user(session: Session) -> User:
    user = User()
    session.add(user)
    session.flush()
    return user


def test_create_signup_returns_201_and_persists(client, session) -> None:
    response = client.post("/signups", json={"site_name": "Example Shop", "site_domain": "Shop.Example.com"})
    assert response.status_code == 201
    body = response.json()
    assert body["site_name"] == "Example Shop"
    assert body["site_domain"] == "shop.example.com"
    assert body["real_name_required"] is False and body["real_name_used"] is False
    assert body["nickname"] in nickname_generator.NICKNAMES
    assert re.fullmatch(ALIAS_PATTERN, body["alias"])
    assert not any("verif" in key for key in body)

    session.expire_all()
    saved = session.get(Signup, body["id"])
    assert saved is not None
    assert saved.alias == body["alias"]
    assert saved.nickname == body["nickname"]
    assert saved.created_at.tzinfo is not None


def test_list_get_and_pagination(client) -> None:
    ids = [client.post("/signups", json={"site_name": f"Site {i}"}).json()["id"] for i in range(3)]

    listing = client.get("/signups").json()
    assert listing["total"] == 3
    assert [item["id"] for item in listing["items"]] == ids[::-1]  # newest first

    page = client.get("/signups?limit=2&offset=1").json()
    assert [item["id"] for item in page["items"]] == [ids[1], ids[0]]
    assert (page["limit"], page["offset"], page["total"]) == (2, 1, 3)

    detail = client.get(f"/signups/{ids[0]}")
    assert detail.status_code == 200
    assert detail.json()["site_name"] == "Site 0"


def test_list_filters_by_normalized_domain(client) -> None:
    client.post("/signups", json={"site_name": "A", "site_domain": "a.example.com"})
    client.post("/signups", json={"site_name": "B", "site_domain": "b.example.com"})
    listing = client.get("/signups?site_domain=A.Example.COM").json()
    assert [item["site_name"] for item in listing["items"]] == ["A"]


def test_unknown_signup_returns_404(client) -> None:
    assert client.get("/signups/987654321").status_code == 404
    assert client.delete("/signups/987654321").status_code == 404


def test_real_name_required_skips_nickname_but_keeps_alias(client) -> None:
    body = client.post("/signups", json={"site_name": "Bank", "real_name_required": True}).json()
    assert body["nickname"] is None
    assert body["alias"] is not None
    assert body["real_name_required"] is True and body["real_name_used"] is True


def test_real_name_required_with_explicit_nickname(client) -> None:
    body = client.post(
        "/signups",
        json={"site_name": "Forum", "real_name_required": True, "generate_nickname": True},
    ).json()
    assert body["nickname"] in nickname_generator.NICKNAMES


def test_surname_variant_is_stored(client, session) -> None:
    body = client.post("/signups", json={"site_name": "Shop", "surname_variant": " Dhingraa "}).json()
    assert body["surname_variant"] == "Dhingraa"
    assert session.get(Signup, body["id"]).surname_variant == "Dhingraa"


def test_markers_can_be_disabled(client) -> None:
    body = client.post(
        "/signups", json={"site_name": "Shop", "generate_alias": False, "generate_nickname": False}
    ).json()
    assert body["alias"] is None and body["nickname"] is None


def test_signups_belong_to_the_signed_in_user(client, session, alice) -> None:
    body = client.post("/signups", json={"site_name": "Shop"}).json()
    assert body["user_id"] == alice.id
    assert session.get(Signup, body["id"]).user_id == alice.id


@pytest.mark.parametrize("user_id", [987654321, 1, 2])
def test_client_supplied_user_id_is_rejected_without_saving(client, session, user_id) -> None:
    before = signup_count(session)
    response = client.post("/signups", json={"site_name": "Shop", "user_id": user_id})
    assert response.status_code == 422
    assert signup_count(session) == before


def test_signed_out_requests_are_refused(session) -> None:
    app.dependency_overrides[get_db] = lambda: session
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    try:
        for method, path, body in [("post", "/signups", {"site_name": "Shop"}), ("get", "/signups", None),
                                   ("get", "/signups/1", None), ("delete", "/signups/1", None)]:
            response = anonymous.request(method.upper(), path, json=body)
            assert response.status_code == 401, (method, path)
    finally:
        app.dependency_overrides.clear()


def test_other_users_signups_are_invisible_and_untouchable(client, bob_client, session) -> None:
    alice_signup = client.post("/signups", json={"site_name": "Alice Shop", "site_domain": "shop.example.com"}).json()
    session.add(Signup(site_name="Historical", site_domain="shop.example.com", alias="hist@leaktrap.xyz"))
    session.commit()
    unowned_id = session.scalar(select(Signup.id).where(Signup.site_name == "Historical"))

    listing = bob_client.get("/signups").json()
    assert listing["total"] == 0 and listing["items"] == []
    assert bob_client.get("/signups", params={"site_domain": "shop.example.com"}).json()["total"] == 0
    for signup_id in (alice_signup["id"], unowned_id, 987654321):
        assert bob_client.get(f"/signups/{signup_id}").status_code == 404
        assert bob_client.delete(f"/signups/{signup_id}").status_code == 404
    # Alice cannot see the unowned historical record either.
    assert client.get(f"/signups/{unowned_id}").status_code == 404
    assert [i["id"] for i in client.get("/signups").json()["items"]] == [alice_signup["id"]]
    # Nothing was deleted by Bob's attempts.
    assert session.get(Signup, alice_signup["id"]) is not None and session.get(Signup, unowned_id) is not None


def test_new_aliases_have_eight_characters_by_default(client) -> None:
    app.dependency_overrides[get_alias_config] = lambda: AliasConfig(domain="aliases.test.example")
    alias = client.post("/signups", json={"site_name": "Shop"}).json()["alias"]
    assert re.fullmatch(r"[a-z0-9]{8}@aliases\.test\.example", alias)


def test_missing_alias_domain_returns_503_without_saving(client, session) -> None:
    app.dependency_overrides[get_alias_config] = lambda: AliasConfig(domain=None)
    before = signup_count(session)
    response = client.post("/signups", json={"site_name": "Shop"})
    assert response.status_code == 503
    assert "LEAKTRACE_ALIAS_DOMAIN" in response.json()["detail"]
    assert signup_count(session) == before

    ok = client.post("/signups", json={"site_name": "Shop", "generate_alias": False})
    assert ok.status_code == 201 and ok.json()["alias"] is None


def test_delete_keeps_evidence_and_unlinks_it(client, session) -> None:
    signup_id = client.post("/signups", json={"site_name": "Shop"}).json()["id"]
    receipt = ConsentReceipt(signup_id=signup_id, privacy_notice_text="Notice")
    mail = MailLog(signup_id=signup_id, subject="Hello")
    session.add_all([receipt, mail])
    session.commit()

    assert client.delete(f"/signups/{signup_id}").status_code == 204
    assert client.get(f"/signups/{signup_id}").status_code == 404

    session.expire_all()
    assert session.get(ConsentReceipt, receipt.id).signup_id is None
    assert session.get(MailLog, mail.id).signup_id is None


def test_alias_precheck_avoids_existing_alias(client, session, monkeypatch) -> None:
    session.add(Signup(site_name="Old", alias="lt.aaaa@aliases.test.example"))
    session.commit()
    suffixes = iter(["AAAA", "bbbb"])
    monkeypatch.setattr(alias_generator, "random_suffix", lambda n: next(suffixes))

    body = client.post("/signups", json={"site_name": "New"}).json()
    assert body["alias"] == "lt.bbbb@aliases.test.example"


def test_database_unique_violation_is_retried(client, session, monkeypatch) -> None:
    """Simulate a race: the pre-check misses a concurrent insert, so PostgreSQL's
    unique index rejects the row; the service rolls back and retries."""
    session.add(Signup(site_name="Old", alias="lt.aaaa@aliases.test.example"))
    session.commit()
    suffixes = iter(["aaaa", "cccc"])
    monkeypatch.setattr(alias_generator, "random_suffix", lambda n: next(suffixes))
    monkeypatch.setattr(signup_service, "alias_exists", lambda s, a: False)
    before = signup_count(session)

    body = client.post("/signups", json={"site_name": "New"}).json()
    assert body["alias"] == "lt.cccc@aliases.test.example"
    assert signup_count(session) == before + 1


def test_retry_exhaustion_returns_503_without_saving(client, session, monkeypatch) -> None:
    session.add(Signup(site_name="Old", alias="lt.aaaa@aliases.test.example"))
    session.commit()
    monkeypatch.setattr(alias_generator, "random_suffix", lambda n: "aaaa")
    monkeypatch.setattr(signup_service, "alias_exists", lambda s, a: False)
    before = signup_count(session)

    response = client.post("/signups", json={"site_name": "New"})
    assert response.status_code == 503
    assert signup_count(session) == before


def test_nickname_exhaustion_returns_409_without_saving(client, bob_client, session, monkeypatch) -> None:
    monkeypatch.setattr(nickname_generator, "NICKNAMES", ("Falcon", "Zephyr"))
    payload = {"site_name": "Shop"}
    first = client.post("/signups", json=payload).json()["nickname"]
    second = client.post("/signups", json=payload).json()["nickname"]
    assert {first, second} == {"Falcon", "Zephyr"}

    before = signup_count(session)
    response = client.post("/signups", json=payload)
    assert response.status_code == 409
    assert "generate_nickname=false" in response.json()["detail"]
    assert signup_count(session) == before

    # Another account's nicknames are independent.
    assert bob_client.post("/signups", json={"site_name": "Shop"}).status_code == 201


def test_each_account_has_its_own_nickname_scope(client, bob_client, monkeypatch) -> None:
    monkeypatch.setattr(nickname_generator, "NICKNAMES", ("Falcon",))
    assert client.post("/signups", json={"site_name": "A"}).json()["nickname"] == "Falcon"
    assert client.post("/signups", json={"site_name": "B"}).status_code == 409
    assert bob_client.post("/signups", json={"site_name": "A"}).json()["nickname"] == "Falcon"


def test_concurrent_signups_get_distinct_markers(engine: Engine, monkeypatch, caplog) -> None:
    """Four threads race for a pool of four nicknames in one user's scope.

    Every thread picks the first free nickname and then waits until all have
    picked, so all four try to insert the same one at once. PostgreSQL's unique
    index rejects three of them; each rolls back, retries and gets a different
    nickname. A fifth request then reports exhaustion.
    """
    caplog.set_level("INFO", logger="leaktrace.signups")
    monkeypatch.setattr(nickname_generator, "NICKNAMES", ("Falcon", "Zephyr", "Quasar", "Kestrel"))
    barrier = threading.Barrier(4)
    first_pick = threading.local()

    def racing_choose(used_in_scope, used_anywhere):
        nickname = nickname_generator.choose_nickname(
            used_in_scope, used_anywhere, choice=lambda seq: seq[0]
        )
        if not getattr(first_pick, "done", False):
            first_pick.done = True
            barrier.wait(timeout=10)
        return nickname

    monkeypatch.setattr(signup_service, "choose_nickname", racing_choose)
    make_session = sessionmaker(bind=engine, expire_on_commit=False)
    with make_session() as s:
        user = User()
        s.add(user)
        s.commit()
    data = signup_service.NewSignup(
        site_name="Race", site_domain=None, user_id=user.id, real_name_required=False,
        surname_variant=None, generate_alias=True, generate_nickname=True,
    )
    results: list[Signup] = []
    errors: list[BaseException] = []

    def worker() -> None:
        with make_session() as s:
            try:
                results.append(signup_service.create_signup(s, data, ALIAS_CONFIG))
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, errors
        assert sorted(r.nickname for r in results) == ["Falcon", "Kestrel", "Quasar", "Zephyr"]
        assert len({r.alias for r in results}) == 4
        collisions = [r for r in caplog.records if "uq_signups_user_id_nickname_lower" in r.getMessage()]
        assert len(collisions) >= 3

        with make_session() as s, pytest.raises(NicknameExhaustedError):
            signup_service.create_signup(s, data, ALIAS_CONFIG)
        with make_session() as s:
            assert s.scalar(select(func.count()).where(Signup.user_id == user.id)) == 4
    finally:
        with make_session() as s:
            s.execute(delete(Signup).where(Signup.user_id == user.id))
            s.execute(delete(User).where(User.id == user.id))
            s.commit()
