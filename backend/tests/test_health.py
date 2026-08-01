"""Application factory, correlation IDs, and health endpoints (T-004, T-135).

Everything here runs fully offline **except** the one test `T-135` added: readiness reporting
`ready` needs a database that actually answers, and no fake proves it. It takes the throwaway
database `conftest.py` builds and skips with the rest of the integration suite when PostgreSQL is
unreachable, so the offline run is unchanged rather than red.
"""

import json
import tomllib
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import APP_VERSION
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, accept_or_generate_request_id
from app.core.settings import AppEnv, Settings, get_settings
from app.db.session import dispose_engines
from app.main import create_app

# Reserved, guaranteed-closed port: connecting fails immediately instead of hanging.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/absent"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.fixture
def unreachable_db_client() -> Iterator[TestClient]:
    """An app whose database certainly does not answer."""
    app = create_app(configure_logs=False)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        app_env=AppEnv.TEST,
        database_url=UNREACHABLE_DATABASE_URL,
    )
    with TestClient(app) as client:
        yield client
    dispose_engines()


@pytest.fixture
def live_db_client(database_url: str) -> Iterator[TestClient]:
    """An app pointed at the session's real PostgreSQL (T-135).

    `database_url` is `conftest.py`'s throwaway database, and taking it here buys the skip as
    well as the connection: when the server is unreachable that fixture skips, so this test does
    too, rather than failing an offline run.

    Deliberately the **unmigrated** database — `/readyz` round-trips `SELECT 1` and must not
    depend on any schema. Readiness that needed a table would report `not_ready` on a fresh
    deployment between `upgrade head` and the first request, which is the opposite of what an
    operator reads it for.
    """
    app = create_app(configure_logs=False)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        app_env=AppEnv.TEST,
        database_url=database_url,
    )
    with TestClient(app) as client:
        yield client
    dispose_engines()


def test_readyz_is_200_against_a_live_database(live_db_client: TestClient) -> None:
    """`T-004` criterion 2's other half: the 503 path was provable offline, this was not."""
    response = live_db_client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    # The failure path returns a `detail`; the success path has nothing to explain, and an
    # operator reading a field that is only ever populated on failure should see it absent.
    assert body["detail"] is None


def test_readyz_still_reports_shadow_mode_when_ready(live_db_client: TestClient) -> None:
    """Asserted on the ready path too, not only the failing one: the safety posture is what
    §17.5 wants visible, and an operator checks it when things are working."""
    assert live_db_client.get("/readyz").json()["shadow_mode"] is True


def test_healthz_is_200_without_a_database(unreachable_db_client: TestClient) -> None:
    response = unreachable_db_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": APP_VERSION}


def test_readyz_is_503_without_a_database(unreachable_db_client: TestClient) -> None:
    response = unreachable_db_client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "unavailable"


def test_readyz_failure_detail_leaks_no_connection_string(
    unreachable_db_client: TestClient,
) -> None:
    """A driver error can quote host, port, and user; only the exception type may surface."""
    body = unreachable_db_client.get("/readyz").text

    for secret_fragment in ("nobody", "nothing", "127.0.0.1", "absent"):
        assert secret_fragment not in body


def test_readyz_reports_shadow_mode(unreachable_db_client: TestClient) -> None:
    """Operators must be able to see the safety posture without reading configuration."""
    assert unreachable_db_client.get("/readyz").json()["shadow_mode"] is True


def test_supplied_request_id_is_echoed(unreachable_db_client: TestClient) -> None:
    response = unreachable_db_client.get("/healthz", headers={REQUEST_ID_HEADER: "abc-123_ok.1"})

    assert response.headers[REQUEST_ID_HEADER] == "abc-123_ok.1"


def test_request_id_is_generated_when_absent(unreachable_db_client: TestClient) -> None:
    response = unreachable_db_client.get("/healthz")

    UUID(response.headers[REQUEST_ID_HEADER])  # raises if it is not a UUID


@pytest.mark.parametrize(
    "hostile",
    [
        "bad\nid",  # log forging via newline
        "bad id",  # whitespace
        "x" * 129,  # unbounded length
        "",  # empty
        '{"json":"injection"}',
        "../../etc/passwd",
    ],
)
def test_hostile_request_id_is_replaced(hostile: str) -> None:
    """Inbound header is untrusted input (specification §15.4)."""
    assert accept_or_generate_request_id(hostile) != hostile
    UUID(accept_or_generate_request_id(hostile))


def test_log_lines_are_json_and_carry_the_correlation_id() -> None:
    """Parse real rendered output rather than trusting a mock."""
    stream = StringIO()
    configure_logging(AppEnv.TEST, stream=stream)

    app = create_app(configure_logs=False)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        app_env=AppEnv.TEST,
        database_url=UNREACHABLE_DATABASE_URL,
    )
    with TestClient(app) as client:
        client.get("/healthz", headers={REQUEST_ID_HEADER: "trace-me-42"})
    dispose_engines()

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    completed = [line for line in lines if line.get("event") == "request.completed"]

    assert completed, f"no request.completed line in {lines}"
    entry = completed[0]
    assert entry["correlation_id"] == "trace-me-42"
    assert entry["app_version"] == APP_VERSION
    assert entry["app_env"] == AppEnv.TEST.value
    assert entry["status_code"] == 200
    assert entry["path"] == "/healthz"
    assert "timestamp" in entry


def test_app_version_matches_pyproject() -> None:
    """The version is reported in logs and OpenAPI, so drift would make both lie."""
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]

    assert declared == APP_VERSION


def test_openapi_document_builds(unreachable_db_client: TestClient) -> None:
    schema = unreachable_db_client.get("/openapi.json").json()

    assert schema["info"]["version"] == APP_VERSION
    assert set(schema["paths"]) >= {"/healthz", "/readyz"}
