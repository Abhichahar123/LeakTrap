"""Autofill alias recall: local-only guard and validation. No database needed."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.database import get_db
from backend.main import app
from tests.auth_support import FAKE_HEADERS, fake_auth
from backend.routes.dashboard import DashboardConfig, get_dashboard_config

LOCAL = ("127.0.0.1", 50000)


class BrokenSession:
    def _fail(self, *args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("postgresql://user:pw@host/db refused"))

    get = scalar = scalars = execute = _fail


@pytest.fixture(autouse=True)
def overrides():
    app.dependency_overrides[get_db] = lambda: None
    fake_auth(app)
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=True)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def local():
    return TestClient(app, client=LOCAL, headers=FAKE_HEADERS)


@pytest.mark.parametrize(
    "body",
    [{}, {"site_domain": ""}, {"site_domain": "localhost"}, {"site_domain": "https://shop.example.com"},
     {"site_domain": "shop.example.com/login"}, {"site_domain": "127.0.0.1"}, {"site_domain": 5},
     {"site_domain": "shop.example.com", "user_id": 1}, {"site_domain": "shop.example.com", "create": True}],
)
def test_invalid_lookup_is_422(local, body) -> None:
    assert local.post("/autofill/lookup", json=body).status_code == 422


def test_get_is_not_allowed(local) -> None:
    assert local.get("/autofill/lookup", params={"site_domain": "shop.example.com"}).status_code == 405


def test_non_local_client_is_refused() -> None:
    response = TestClient(app, client=("203.0.113.5", 50000)).post("/autofill/lookup", json={"site_domain": "shop.example.com"})
    assert response.status_code == 403


def test_disabled_is_404(local) -> None:
    app.dependency_overrides[get_dashboard_config] = lambda: DashboardConfig(enabled=False)
    assert local.post("/autofill/lookup", json={"site_domain": "shop.example.com"}).status_code == 404


@pytest.mark.parametrize("params", [{}, {"user_id": 3}])
def test_database_failure_is_503_without_details(local, params) -> None:
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    response = local.post("/autofill/lookup", params=params, json={"site_domain": "shop.example.com"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}


def test_existing_routes_still_registered() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    for path in ("/signups", "/signups/{signup_id}", "/matcher/check", "/ingest/email", "/consent-receipts",
                 "/dashboard/api/overview", "/autofill/lookup"):
        assert path in paths
