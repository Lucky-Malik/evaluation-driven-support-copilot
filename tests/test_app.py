import psycopg
import pytest
from fastapi.testclient import TestClient

from support_copilot.app import app


def test_health_is_independent_of_database():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_ready_returns_success_after_database_check(monkeypatch):
    monkeypatch.setattr("support_copilot.app.database_url", lambda: "test-url")
    monkeypatch.setattr("support_copilot.app.check_ready", lambda _: None)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError("password=secret"),
        psycopg.errors.UndefinedTable("private schema details"),
        ValueError("DATABASE_URL secret"),
    ],
)
def test_not_ready_does_not_expose_error_details(monkeypatch, capsys, error):
    def fail(_):
        raise error

    monkeypatch.setattr("support_copilot.app.database_url", lambda: "test-url")
    monkeypatch.setattr("support_copilot.app.check_ready", fail)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "secret" not in response.text + capsys.readouterr().err
