"""Flask application factory and routes."""

from __future__ import annotations

from typing import Any, Literal

from flask import Flask, Response, current_app, g, jsonify, request
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.exceptions import HTTPException

from structflow import weighted_average_life
from structflow_api import models, service
from structflow_api.db import database_url, make_engine, make_sessionmaker
from structflow_api.openapi import SWAGGER_HTML, build_spec
from structflow_api.schemas import (
    CashFlowResponse,
    CashFlowRow,
    PoolCreate,
    PoolList,
    PoolOut,
    PriceRequest,
    PriceResponse,
    Scenario,
    ScenarioQuery,
    ScenarioResponse,
    ScenarioResult,
)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


Reply = tuple[Response, int]


def _error(
    status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> Reply:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    return jsonify(body), status


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": [str(p) if not isinstance(p, int) else p for p in e["loc"]], "msg": e["msg"]}
        for e in exc.errors(include_url=False, include_input=False)
    ]


def _db() -> Session:
    if "db" not in g:
        factory: sessionmaker[Session] = current_app.extensions["sessionmaker"]
        g.db = factory()
    session: Session = g.db
    return session


def _json_body() -> Any:
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError(400, "bad_request", "request body must be a JSON object")
    return body


def _dump(model: BaseModel, status: int = 200) -> Reply:
    return current_app.response_class(
        model.model_dump_json(by_alias=True), mimetype="application/json"
    ), status


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_URL"] = database_url()
    app.config.update(config or {})
    engine = make_engine(app.config["DATABASE_URL"])
    app.extensions["engine"] = engine
    app.extensions["sessionmaker"] = make_sessionmaker(engine)

    @app.teardown_appcontext
    def close_db(exc: BaseException | None) -> None:
        session = g.pop("db", None)
        if session is not None:
            if exc is not None:
                session.rollback()
            session.close()

    @app.errorhandler(ApiError)
    def api_error(exc: ApiError) -> Reply:
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.errorhandler(ValidationError)
    def validation_error(exc: ValidationError) -> Reply:
        return _error(
            422, "validation_error", "request failed validation", _validation_details(exc)
        )

    @app.errorhandler(service.NotFound)
    def not_found(exc: service.NotFound) -> Reply:
        return _error(404, "not_found", str(exc))

    @app.errorhandler(service.Conflict)
    def conflict(exc: service.Conflict) -> Reply:
        return _error(409, "conflict", str(exc))

    @app.errorhandler(ValueError)
    def value_error(exc: ValueError) -> Reply:
        # Raised by the pricing library for inputs that pass schema checks but are
        # still not computable, e.g. a price no yield can reach.
        return _error(422, "unprocessable", str(exc))

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException) -> Reply:
        code = (exc.name or "error").lower().replace(" ", "_")
        return _error(exc.code or 500, code, exc.description or "")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/openapi.json")
    def openapi() -> dict[str, Any]:
        return build_spec()

    @app.get("/docs")
    def docs() -> Response:
        return Response(SWAGGER_HTML, mimetype="text/html")

    @app.get("/pools")
    def list_pools() -> Reply:
        pools = _db().scalars(select(models.Pool).order_by(models.Pool.id)).all()
        return _dump(PoolList(pools=[PoolOut.model_validate(p) for p in pools]))

    @app.post("/pools")
    def create_pool() -> Reply:
        data = PoolCreate.model_validate(_json_body())
        session = _db()
        pool = service.create_pool(session, data)
        session.commit()
        return _dump(PoolOut.model_validate(pool), 201)

    @app.get("/pools/<int:pool_id>")
    def get_pool(pool_id: int) -> Reply:
        return _dump(PoolOut.model_validate(service.get_pool(_db(), pool_id)))

    @app.post("/pools/<int:pool_id>/cashflows")
    def cashflows(pool_id: int) -> Reply:
        scenario = Scenario.model_validate(_json_body())
        session = _db()
        tape = service.load_tape(session, service.get_pool(session, pool_id))
        cf = service.project(tape, scenario)
        rows = [CashFlowRow.model_validate(r) for r in cf.to_dict(orient="records")]
        return _dump(
            CashFlowResponse(
                pool_id=pool_id,
                scenario=scenario,
                wal=weighted_average_life(cf["total_principal"].to_numpy()),
                rows=rows,
            )
        )

    @app.post("/pools/<int:pool_id>/price")
    def price(pool_id: int) -> Reply:
        req = PriceRequest.model_validate(_json_body())
        scenario = Scenario(model=req.model, speed=req.speed)
        session = _db()
        pool = service.get_pool(session, pool_id)
        cf = service.project(service.load_tape(session, pool), scenario)
        result = service.analytics(cf, yld=req.yield_, price=req.price)
        inputs = {"yield": result.yield_} if req.yield_ is not None else {"price": result.price}
        run = service.record_run(session, pool, scenario, result, kind="price", inputs=inputs)
        session.commit()
        return _dump(
            PriceResponse(pool_id=pool_id, run_id=run.id, scenario=scenario, **result.to_dict())
        )

    @app.get("/pools/<int:pool_id>/scenarios")
    def scenarios(pool_id: int) -> Reply:
        query = ScenarioQuery.model_validate(request.args.to_dict())
        session = _db()
        pool = service.get_pool(session, pool_id)
        tape = service.load_tape(session, pool)
        if query.price is not None:
            grid = service.scenario_grid(tape, price=query.price)
            basis: Literal["yield", "price"] = "price"
            value = query.price
        else:
            value = query.yield_ if query.yield_ is not None else pool.pass_through_rate
            grid = service.scenario_grid(tape, yld=value)
            basis = "yield"
        return _dump(
            ScenarioResponse(
                pool_id=pool_id,
                basis=basis,
                value=value,
                scenarios=[ScenarioResult(scenario=s, **r.to_dict()) for s, r in grid],
            )
        )

    return app
