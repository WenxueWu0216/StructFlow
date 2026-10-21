import pytest

from structflow_api import create_app
from structflow_api.models import Base

LOANS = [
    {"loan_id": "A", "balance": 200_000, "note_rate": 0.0625, "remaining_term": 360, "age": 0},
    {"loan_id": "B", "balance": 300_000, "note_rate": 0.0675, "remaining_term": 348, "age": 12},
]
POOL = {"name": "TEST-1", "pass_through_rate": 0.055, "loans": LOANS}


@pytest.fixture
def app():
    app = create_app({"DATABASE_URL": "sqlite+pysqlite:///:memory:", "TESTING": True})
    Base.metadata.create_all(app.extensions["engine"])
    yield app
    app.extensions["engine"].dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def pool_id(client):
    resp = client.post("/pools", json=POOL)
    assert resp.status_code == 201, resp.json
    return resp.json["id"]
