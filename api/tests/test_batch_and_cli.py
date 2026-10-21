from datetime import date

import pytest
from sqlalchemy import func, select
from tests.conftest import POOL

from structflow_api import cli, models, service
from structflow_api.db import make_engine, make_sessionmaker, session_scope
from structflow_api.models import Base
from structflow_api.schemas import PoolCreate


@pytest.fixture
def sessions():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)


def _add_curve(session, as_of=date(2026, 10, 20)):
    curve = models.RateCurve(name="UST", as_of=as_of)
    curve.points = [
        models.RateCurvePoint(tenor_years=2, rate=0.04),
        models.RateCurvePoint(tenor_years=10, rate=0.045),
    ]
    session.add(curve)


def test_reprice_all_uses_curve_plus_spread_and_is_idempotent(sessions):
    with session_scope(sessions) as session:
        service.create_pool(session, PoolCreate(**POOL))
        service.create_pool(session, PoolCreate(**{**POOL, "name": "TEST-2"}))
        _add_curve(session)

    for _ in range(2):
        with session_scope(sessions) as session:
            runs = service.reprice_all(session, date(2026, 10, 21), spread_bps=120)

    with session_scope(sessions) as session:
        assert session.scalar(select(func.count()).select_from(models.Run)) == 2
        run = session.scalars(select(models.Run)).first()
    # yield = interpolated curve at WAL + 120 bp
    # curve is linear between 2y (4.0%) and 10y (4.5%): rate(w) = 0.04 + (w - 2) * 0.005 / 8
    expected_curve = 0.04 + (run.wal - 2) * 0.005 / 8
    assert run.inputs["curve_rate"] == pytest.approx(expected_curve)
    assert run.yield_ == pytest.approx(expected_curve + 0.012)
    assert (run.kind, run.as_of, run.prepay_model, run.speed) == (
        "batch",
        date(2026, 10, 21),
        "PSA",
        150,
    )
    assert len(runs) == 2


def test_reprice_without_curve_fails(sessions):
    with session_scope(sessions) as session, pytest.raises(service.NotFound):
        service.reprice_all(session, date(2026, 10, 21))


def test_reprice_uses_latest_curve_not_after_as_of(sessions):
    with session_scope(sessions) as session:
        _add_curve(session, date(2026, 10, 1))
        _add_curve(session, date(2026, 10, 30))
        assert service.latest_curve(session, "UST", date(2026, 10, 21)).as_of == date(2026, 10, 1)


def test_cli_end_to_end(tmp_path, capsys):
    url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    Base.metadata.create_all(make_engine(url))
    tape = tmp_path / "pool.csv"
    curve = tmp_path / "curve.csv"
    curve.write_text("as_of,tenor_years,rate\n2026-10-20,1,0.04\n2026-10-20,10,0.045\n")

    assert cli.main(["generate-pool", str(tape), "--loans", "1000"]) == 0
    assert (
        cli.main(
            [
                "--database-url",
                url,
                "ingest",
                str(tape),
                "--name",
                "SYN",
                "--pass-through-rate",
                "0.055",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "--database-url",
                url,
                "ingest",
                str(tape),
                "--name",
                "SYN",
                "--pass-through-rate",
                "0.055",
            ]
        )
        == 1
    )
    assert cli.main(["--database-url", url, "load-curve", str(curve)]) == 0
    assert cli.main(["--database-url", url, "reprice", "--as-of", "2026-10-21"]) == 0
    out = capsys.readouterr().out
    assert "1000 loans" in out and "repriced 1 pools" in out

    with session_scope(make_sessionmaker(make_engine(url))) as session:
        assert session.scalar(select(func.count()).select_from(models.Loan)) == 1000


def test_cli_rejects_bad_tape(tmp_path, capsys):
    url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    Base.metadata.create_all(make_engine(url))
    bad = tmp_path / "bad.csv"
    bad.write_text("loan_id,balance,note_rate,remaining_term,age\nX,-1,0.06,360,0\n")
    assert (
        cli.main(
            [
                "--database-url",
                url,
                "ingest",
                str(bad),
                "--name",
                "BAD",
                "--pass-through-rate",
                "0.05",
            ]
        )
        == 2
    )
    assert "failed validation" in capsys.readouterr().err
