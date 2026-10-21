import pytest
from sqlalchemy import select
from tests.conftest import LOANS, POOL

import structflow
from structflow_api import models


def test_create_pool_returns_weighted_summary(client):
    resp = client.post("/pools", json=POOL)
    assert resp.status_code == 201
    body = resp.json
    # WAC = (200k * 6.25% + 300k * 6.75%) / 500k = 6.55%
    # WAM = (200k * 360 + 300k * 348) / 500k = 352.8 -> 353; WALA = 300k * 12 / 500k = 7.2 -> 7
    assert body["balance"] == 500_000
    assert body["wac"] == pytest.approx(0.0655)
    assert (body["wam"], body["wala"], body["loan_count"]) == (353, 7, 2)
    assert client.get(f"/pools/{body['id']}").json == body
    assert [p["id"] for p in client.get("/pools").json["pools"]] == [body["id"]]


def test_duplicate_pool_name_conflicts(client, pool_id):
    resp = client.post("/pools", json=POOL)
    assert resp.status_code == 409
    assert resp.json["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("patch", "loc"),
    [
        ({"loans": []}, ["loans"]),
        ({"pass_through_rate": 1.5}, ["pass_through_rate"]),
        ({"loans": [{**LOANS[0], "balance": -5}]}, ["loans", 0, "balance"]),
        ({"loans": [{**LOANS[0], "remaining_term": 0}]}, ["loans", 0, "remaining_term"]),
        ({"loans": [{**LOANS[0], "note_rate": 0.05}]}, []),  # below pass-through
        ({"loans": [LOANS[0], LOANS[0]]}, []),  # duplicate loan ids
        ({"surprise": 1}, ["surprise"]),
    ],
)
def test_create_pool_validation(client, patch, loc):
    resp = client.post("/pools", json={**POOL, **patch})
    assert resp.status_code == 422
    err = resp.json["error"]
    assert err["code"] == "validation_error"
    assert err["details"] and err["details"][0]["loc"] == loc


def test_non_json_body_is_400(client):
    resp = client.post("/pools", data="nope", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "bad_request"


def test_unknown_pool_is_404(client):
    for resp in (
        client.get("/pools/99"),
        client.post("/pools/99/cashflows", json={"model": "PSA", "speed": 100}),
        client.post("/pools/99/price", json={"model": "PSA", "speed": 100, "yield": 0.05}),
        client.get("/pools/99/scenarios"),
    ):
        assert resp.status_code == 404
        assert resp.json["error"]["code"] == "not_found"


def test_unknown_route_returns_json_error(client):
    resp = client.get("/nowhere")
    assert resp.status_code == 404
    assert resp.json["error"]["code"] == "not_found"


def _library_tape():
    return structflow.LoanTape(
        balance=[loan["balance"] for loan in LOANS],
        note_rate=[loan["note_rate"] for loan in LOANS],
        remaining_term=[loan["remaining_term"] for loan in LOANS],
        age=[loan["age"] for loan in LOANS],
        pass_through_rate=0.055,
    )


def test_cashflows_match_library(client, pool_id):
    resp = client.post(f"/pools/{pool_id}/cashflows", json={"model": "PSA", "speed": 150})
    assert resp.status_code == 200
    body = resp.json
    expected = structflow.project_cashflows(_library_tape(), structflow.PSA(150))
    assert len(body["rows"]) == 360
    assert body["rows"][0]["month"] == 1
    assert sum(r["total_principal"] for r in body["rows"]) == pytest.approx(500_000)
    assert [r["cash_flow"] for r in body["rows"]] == pytest.approx(expected["cash_flow"].tolist())
    assert body["wal"] == pytest.approx(
        structflow.weighted_average_life(expected["total_principal"])
    )


@pytest.mark.parametrize(
    "scenario",
    [
        {"model": "ABS", "speed": 1},
        {"model": "PSA", "speed": -1},
        {"model": "CPR", "speed": 101},
        {"model": "PSA"},
        {"model": "PSA", "speed": "fast"},
    ],
)
def test_cashflow_scenario_validation(client, pool_id, scenario):
    resp = client.post(f"/pools/{pool_id}/cashflows", json=scenario)
    assert resp.status_code == 422


def test_price_from_yield_and_back(client, pool_id):
    resp = client.post(f"/pools/{pool_id}/price", json={"model": "CPR", "speed": 8, "yield": 0.05})
    assert resp.status_code == 200
    priced = resp.json
    assert priced["price"] > 100  # yield below the 5.5% coupon -> premium
    assert priced["scenario"] == {"model": "CPR", "speed": 8}

    resp = client.post(
        f"/pools/{pool_id}/price", json={"model": "CPR", "speed": 8, "price": priced["price"]}
    )
    solved = resp.json
    assert solved["yield"] == pytest.approx(0.05, abs=1e-9)
    assert solved["wal"] == pytest.approx(priced["wal"])
    assert solved["run_id"] != priced["run_id"]


def test_price_records_run(app, client, pool_id):
    run_id = client.post(
        f"/pools/{pool_id}/price", json={"model": "PSA", "speed": 100, "yield": 0.055}
    ).json["run_id"]
    with app.extensions["sessionmaker"]() as session:
        run = session.get(models.Run, run_id)
        assert (run.kind, run.prepay_model, run.speed) == ("price", "PSA", 100)
        assert run.price == pytest.approx(100.0)  # priced at its coupon -> par
        assert run.library_version == structflow.__version__


@pytest.mark.parametrize(
    "body",
    [
        {"model": "PSA", "speed": 100},
        {"model": "PSA", "speed": 100, "yield": 0.05, "price": 101},
        {"model": "PSA", "speed": 100, "price": 0},
    ],
)
def test_price_needs_exactly_one_of_yield_or_price(client, pool_id, body):
    assert client.post(f"/pools/{pool_id}/price", json=body).status_code == 422


def test_unreachable_price_is_unprocessable(client, pool_id):
    resp = client.post(
        f"/pools/{pool_id}/price", json={"model": "PSA", "speed": 100, "price": 0.01}
    )
    assert resp.status_code == 422
    assert resp.json["error"]["code"] == "unprocessable"


def test_scenarios_default_to_pass_through_yield(client, pool_id):
    body = client.get(f"/pools/{pool_id}/scenarios").json
    assert (body["basis"], body["value"]) == ("yield", 0.055)
    speeds = [s["scenario"]["speed"] for s in body["scenarios"]]
    assert speeds == sorted(speeds) and len(speeds) == 7
    assert all(s["price"] == pytest.approx(100.0) for s in body["scenarios"])
    wals = [s["wal"] for s in body["scenarios"]]
    assert wals == sorted(wals, reverse=True)


def test_scenarios_at_a_discount_price(client, pool_id):
    body = client.get(f"/pools/{pool_id}/scenarios?price=95").json
    assert body["basis"] == "price"
    yields = [s["yield"] for s in body["scenarios"]]
    # A discount bond earns its discount back faster when prepayments speed up.
    assert yields == sorted(yields)
    assert client.get(f"/pools/{pool_id}/scenarios?price=95&yield=0.05").status_code == 422
    assert client.get(f"/pools/{pool_id}/scenarios?yield=abc").status_code == 422


def test_openapi_and_docs(client):
    spec = client.get("/openapi.json").json
    assert spec["openapi"].startswith("3.")
    assert set(spec["paths"]) == {
        "/pools",
        "/pools/{pool_id}",
        "/pools/{pool_id}/cashflows",
        "/pools/{pool_id}/price",
        "/pools/{pool_id}/scenarios",
    }
    refs = {"PoolCreate", "Scenario", "PriceRequest", "ScenarioResponse", "ErrorResponse"}
    assert refs <= set(spec["components"]["schemas"])
    assert "yield" in spec["components"]["schemas"]["PriceRequest"]["properties"]
    assert b"swagger-ui" in client.get("/docs").data


def test_pool_delete_cascades_loans(app, pool_id):
    with app.extensions["sessionmaker"]() as session:
        session.delete(session.get(models.Pool, pool_id))
        session.commit()
        assert session.scalars(select(models.Loan)).all() == []
