"""Command line entry points: ``structflow <command>``.

generate-pool  write a synthetic loan tape CSV
ingest         load a loan tape CSV as a new pool
load-curve     load a rate curve CSV (as_of, tenor_years, rate)
reprice        nightly batch: reprice every pool against the latest curve
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from structflow_api import models, service
from structflow_api.db import database_url, make_engine, make_sessionmaker, session_scope
from structflow_api.schemas import PoolCreate
from structflow_api.synthetic import synthetic_tape

LOAN_COLUMNS = ["loan_id", "balance", "note_rate", "remaining_term", "age"]


def _sessions(url: str | None) -> sessionmaker[Session]:
    return make_sessionmaker(make_engine(url or database_url()))


def cmd_generate(args: argparse.Namespace) -> int:
    tape = synthetic_tape(args.loans, args.pass_through_rate, args.seed)
    tape.to_csv(args.output, index=False)
    print(f"wrote {len(tape)} loans, balance {tape['balance'].sum():,.2f}, to {args.output}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    frame = pd.read_csv(args.path, dtype={"loan_id": str})
    missing = sorted(set(LOAN_COLUMNS) - set(frame.columns))
    if missing:
        print(f"error: missing columns: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        data = PoolCreate(
            name=args.name,
            pass_through_rate=args.pass_through_rate,
            loans=frame[LOAN_COLUMNS].to_dict(orient="records"),
        )
    except ValidationError as exc:
        print(f"error: pool file failed validation:\n{exc}", file=sys.stderr)
        return 2
    try:
        with session_scope(_sessions(args.database_url)) as session:
            pool = service.create_pool(session, data)
            print(
                f"pool {pool.id} {pool.name!r}: {pool.loan_count} loans, "
                f"balance {pool.balance:,.2f}, WAC {pool.wac:.4%}, WAM {pool.wam}, WALA {pool.wala}"
            )
    except service.Conflict as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_load_curve(args: argparse.Namespace) -> int:
    frame = pd.read_csv(args.path, parse_dates=["as_of"])
    with session_scope(_sessions(args.database_url)) as session:
        for as_of, group in frame.groupby("as_of"):
            day = pd.Timestamp(as_of).date()  # type: ignore[arg-type]
            existing = session.scalar(
                select(models.RateCurve).where(
                    models.RateCurve.name == args.name, models.RateCurve.as_of == day
                )
            )
            if existing is not None:
                session.delete(existing)
                session.flush()
            curve = models.RateCurve(name=args.name, as_of=day)
            curve.points = [
                models.RateCurvePoint(tenor_years=float(t), rate=float(r))
                for t, r in group.sort_values("tenor_years")[["tenor_years", "rate"]].itertuples(
                    index=False
                )
            ]
            session.add(curve)
            print(f"curve {args.name} {day}: {len(curve.points)} points")
    return 0


def cmd_reprice(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    try:
        with session_scope(_sessions(args.database_url)) as session:
            runs = service.reprice_all(session, as_of, args.curve, args.spread_bps)
            for run in runs:
                print(
                    f"pool {run.pool_id}: {run.prepay_model} {run.speed:g} "
                    f"yield {run.yield_:.4%} price {run.price:.4f} WAL {run.wal:.2f} "
                    f"mod dur {run.modified_duration:.2f}"
                )
            print(f"repriced {len(runs)} pools as of {as_of}")
    except service.NotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="structflow", description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", help="defaults to $DATABASE_URL")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-pool", help="write a synthetic loan tape CSV")
    gen.add_argument("output", type=Path)
    gen.add_argument("--loans", type=int, default=1_000)
    gen.add_argument("--pass-through-rate", type=float, default=0.055)
    gen.add_argument("--seed", type=int, default=7)
    gen.set_defaults(func=cmd_generate)

    ing = sub.add_parser("ingest", help="load a loan tape CSV as a new pool")
    ing.add_argument("path", type=Path)
    ing.add_argument("--name", required=True)
    ing.add_argument("--pass-through-rate", type=float, required=True)
    ing.set_defaults(func=cmd_ingest)

    crv = sub.add_parser("load-curve", help="load a rate curve CSV")
    crv.add_argument("path", type=Path)
    crv.add_argument("--name", default="UST")
    crv.set_defaults(func=cmd_load_curve)

    rep = sub.add_parser("reprice", help="reprice all pools (nightly batch)")
    rep.add_argument("--as-of", help="YYYY-MM-DD, defaults to today")
    rep.add_argument("--curve", default="UST")
    rep.add_argument("--spread-bps", type=float, default=service.DEFAULT_SPREAD_BPS)
    rep.set_defaults(func=cmd_reprice)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
