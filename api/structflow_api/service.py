"""Glue between the database and the structflow library.

Both the HTTP handlers and the nightly batch call these functions, so the API
and the batch always price a pool the same way.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

import structflow
from structflow_api import models
from structflow_api.schemas import PoolCreate, Scenario

STANDARD_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(model="PSA", speed=0),
    Scenario(model="PSA", speed=50),
    Scenario(model="PSA", speed=100),
    Scenario(model="PSA", speed=150),
    Scenario(model="PSA", speed=200),
    Scenario(model="PSA", speed=300),
    Scenario(model="PSA", speed=500),
)

# Base case the nightly batch uses: nominal spread over the curve at the pool's WAL.
BATCH_SCENARIO = Scenario(model="PSA", speed=150)
DEFAULT_SPREAD_BPS = 100.0


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def create_pool(session: Session, data: PoolCreate) -> models.Pool:
    if session.scalar(select(models.Pool.id).where(models.Pool.name == data.name)) is not None:
        raise Conflict(f"a pool named {data.name!r} already exists")
    tape = structflow.LoanTape(
        balance=[loan.balance for loan in data.loans],
        note_rate=[loan.note_rate for loan in data.loans],
        remaining_term=[loan.remaining_term for loan in data.loans],
        age=[loan.age for loan in data.loans],
        pass_through_rate=data.pass_through_rate,
    )
    summary = tape.summary()
    pool = models.Pool(
        name=data.name,
        pass_through_rate=data.pass_through_rate,
        balance=summary.balance,
        wac=summary.wac,
        wam=summary.wam,
        wala=summary.wala,
        loan_count=len(tape),
    )
    session.add(pool)
    session.flush()
    session.execute(
        insert(models.Loan),
        [{"pool_id": pool.id, **loan.model_dump()} for loan in data.loans],
    )
    return pool


def get_pool(session: Session, pool_id: int) -> models.Pool:
    pool = session.get(models.Pool, pool_id)
    if pool is None:
        raise NotFound(f"pool {pool_id} not found")
    return pool


def load_tape(session: Session, pool: models.Pool) -> structflow.LoanTape:
    rows = session.execute(
        select(
            models.Loan.balance,
            models.Loan.note_rate,
            models.Loan.remaining_term,
            models.Loan.age,
        )
        .where(models.Loan.pool_id == pool.id)
        .order_by(models.Loan.id)
    ).all()
    if not rows:
        raise NotFound(f"pool {pool.id} has no loans")
    arr = np.array(rows, dtype=np.float64)
    return structflow.LoanTape(
        balance=arr[:, 0],
        note_rate=arr[:, 1],
        remaining_term=arr[:, 2],
        age=arr[:, 3],
        pass_through_rate=pool.pass_through_rate,
    )


def project(tape: structflow.LoanTape, scenario: Scenario) -> pd.DataFrame:
    return structflow.project_cashflows(tape, structflow.make_model(scenario.model, scenario.speed))


def analytics(
    cf: pd.DataFrame, *, yld: float | None = None, price: float | None = None
) -> structflow.PricingResult:
    if yld is not None:
        return structflow.analytics_from_yield(cf, yld)
    if price is not None:
        return structflow.analytics_from_price(cf, price)
    raise ValueError("need a yield or a price")


def record_run(
    session: Session,
    pool: models.Pool,
    scenario: Scenario,
    result: structflow.PricingResult,
    *,
    kind: str,
    inputs: dict[str, float],
    as_of: date | None = None,
    curve_id: int | None = None,
) -> models.Run:
    run = models.Run(
        pool_id=pool.id,
        kind=kind,
        as_of=as_of,
        curve_id=curve_id,
        prepay_model=scenario.model,
        speed=scenario.speed,
        library_version=structflow.__version__,
        inputs=inputs,
        price=result.price,
        yield_=result.yield_,
        wal=result.wal,
        modified_duration=result.modified_duration,
        convexity=result.convexity,
    )
    session.add(run)
    session.flush()
    return run


def scenario_grid(
    tape: structflow.LoanTape,
    *,
    yld: float | None = None,
    price: float | None = None,
    scenarios: Iterable[Scenario] = STANDARD_SCENARIOS,
) -> list[tuple[Scenario, structflow.PricingResult]]:
    return [(s, analytics(project(tape, s), yld=yld, price=price)) for s in scenarios]


def latest_curve(session: Session, name: str, as_of: date) -> models.RateCurve:
    curve = session.scalar(
        select(models.RateCurve)
        .where(models.RateCurve.name == name, models.RateCurve.as_of <= as_of)
        .order_by(models.RateCurve.as_of.desc())
        .limit(1)
    )
    if curve is None or not curve.points:
        raise NotFound(f"no {name!r} rate curve on or before {as_of.isoformat()}")
    return curve


def reprice_all(
    session: Session,
    as_of: date,
    curve_name: str = "UST",
    spread_bps: float = DEFAULT_SPREAD_BPS,
    scenario: Scenario = BATCH_SCENARIO,
) -> list[models.Run]:
    """Nightly batch: price every pool at curve(WAL) + spread under the base scenario.

    Re-running for the same ``as_of`` replaces that date's batch runs, so the
    job is safe to retry.
    """
    curve = latest_curve(session, curve_name, as_of)
    tenors = [p.tenor_years for p in curve.points]
    rates = [p.rate for p in curve.points]
    session.execute(delete(models.Run).where(models.Run.kind == "batch", models.Run.as_of == as_of))
    runs = []
    for pool in session.scalars(select(models.Pool).order_by(models.Pool.id)):
        cf = project(load_tape(session, pool), scenario)
        wal = structflow.weighted_average_life(cf["total_principal"].to_numpy())
        base = structflow.interpolate_rate(tenors, rates, wal)
        yld = base + spread_bps / 10_000.0
        result = structflow.analytics_from_yield(cf, yld)
        runs.append(
            record_run(
                session,
                pool,
                scenario,
                result,
                kind="batch",
                as_of=as_of,
                curve_id=curve.id,
                inputs={"curve_rate": base, "spread_bps": spread_bps, "yield": yld},
            )
        )
    return runs
