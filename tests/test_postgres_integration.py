"""Live PostgreSQL integration tests.

Skipped unless TEST_DATABASE_URL is set. The engine and session fixtures,
and the safety checks on the test database, live in tests/conftest.py.
"""

from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import check_database_connection
from backend.models import ConsentReceipt, Incident, LeakEdge, Report, Signup, User
from tests.conftest import PROJECT_ROOT, alembic_config

pytestmark = pytest.mark.integration

def expect_integrity_error(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_connection(engine: Engine) -> None:
    assert check_database_connection(engine) is True


def test_migration_is_at_head_and_matches_models(engine: Engine) -> None:
    head = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini"))).get_current_head()
    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == head
        tables = set(inspect(connection).get_table_names())
        # Raises if autogenerate finds any difference between models and schema.
        command.check(alembic_config(connection))
    assert {
        "users", "signups", "consent_receipts", "mail_log",
        "incidents", "complaint_drafts", "reports", "leak_edges",
    } <= tables


def test_create_and_retrieve_signup(session: Session) -> None:
    user = User()
    session.add(user)
    session.flush()
    session.add(Signup(user_id=user.id, site_name="Example Shop", alias="shop@alias.example"))
    session.flush()
    session.expire_all()

    signup = session.scalars(select(Signup).where(Signup.site_name == "Example Shop")).one()
    assert signup.user_id == user.id
    assert signup.real_name_required is False
    assert signup.real_name_used is False


def test_timestamps_are_timezone_aware(session: Session) -> None:
    signup = Signup(site_name="Example")
    session.add(signup)
    session.flush()
    session.refresh(signup)
    for value in (signup.created_at, signup.updated_at):
        assert value.tzinfo is not None
        assert value.utcoffset() is not None


def test_foreign_key_rejects_missing_user(session: Session) -> None:
    session.add(Signup(user_id=999_999_999, site_name="Example"))
    expect_integrity_error(session)


def test_deleting_user_with_records_raises(session: Session) -> None:
    user = User()
    session.add(user)
    session.flush()
    session.add(Report(user_id=user.id, site_name="Example"))
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(delete(User).where(User.id == user.id))
    session.rollback()


def test_deleting_signup_keeps_consent_receipt(session: Session) -> None:
    signup = Signup(site_name="Example")
    session.add(signup)
    session.flush()
    receipt = ConsentReceipt(signup_id=signup.id, privacy_notice_text="We share your data.")
    session.add(receipt)
    session.flush()

    session.execute(delete(Signup).where(Signup.id == signup.id))
    session.expire_all()

    kept = session.get(ConsentReceipt, receipt.id)
    assert kept is not None
    assert kept.signup_id is None
    assert kept.privacy_notice_text == "We share your data."


def test_alias_is_unique_case_insensitively(session: Session) -> None:
    session.add(Signup(site_name="A", alias="shop@alias.example"))
    session.flush()
    session.add(Signup(site_name="B", alias="SHOP@alias.example"))
    expect_integrity_error(session)


def test_multiple_signups_without_alias_or_nickname_are_allowed(session: Session) -> None:
    session.add_all([Signup(site_name="A"), Signup(site_name="B")])
    session.flush()


def test_nickname_unique_within_owner(session: Session) -> None:
    user = User()
    session.add(user)
    session.flush()
    session.add(Signup(user_id=user.id, site_name="A", nickname="Bluefinch"))
    session.flush()
    session.add(Signup(user_id=user.id, site_name="B", nickname="bluefinch"))
    expect_integrity_error(session)


def test_nickname_unique_among_signups_without_owner(session: Session) -> None:
    session.add(Signup(site_name="A", nickname="Bluefinch"))
    session.flush()
    session.add(Signup(site_name="B", nickname="Bluefinch"))
    expect_integrity_error(session)


def test_same_nickname_allowed_for_different_owners(session: Session) -> None:
    first, second = User(), User()
    session.add_all([first, second])
    session.flush()
    session.add_all([
        Signup(user_id=first.id, site_name="A", nickname="Bluefinch"),
        Signup(user_id=second.id, site_name="B", nickname="Bluefinch"),
    ])
    session.flush()
    # The non-unique lower(nickname) index lets later phases find such collisions.
    count = session.scalar(
        select(func.count()).select_from(Signup).where(func.lower(Signup.nickname) == "bluefinch")
    )
    assert count == 2


def test_jsonb_evidence_round_trip(session: Session) -> None:
    evidence = {"markers": ["Bluefinch", "shop@alias.example"], "score": {"value": 0.9}, "ok": True}
    incident = Incident(channel="sms", message_text="Hi Bluefinch", evidence=evidence)
    edge = LeakEdge(
        source_type="site", source_id="example.com",
        target_type="site", target_id="broker.example",
        relationship_type="shared_with", evidence={"incident_ids": [1, 2]},
    )
    session.add_all([incident, edge])
    session.flush()
    session.expire_all()

    stored = session.get(Incident, incident.id)
    assert stored.evidence == evidence
    found = session.scalars(
        select(Incident.id).where(Incident.evidence["score"]["value"].as_float() > 0.5)
    ).all()
    assert incident.id in found
    assert session.get(LeakEdge, edge.id).evidence == {"incident_ids": [1, 2]}


def test_incident_channel_is_validated(session: Session) -> None:
    session.add(Incident(channel="fax"))
    expect_integrity_error(session)


def test_created_at_uses_database_clock(session: Session) -> None:
    incident = Incident(channel="email")
    session.add(incident)
    session.flush()
    session.refresh(incident)
    db_now = session.scalar(text("SELECT now()"))
    assert abs(db_now - incident.created_at) < timedelta(minutes=1)
