"""Property-based tests: invariants that must hold for any valid pool."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from structflow import (
    CPR,
    PSA,
    LoanTape,
    Pool,
    price_from_yield,
    project_cashflows,
    project_cashflows_naive,
    weighted_average_life,
    yield_from_price,
)

pass_through = st.floats(min_value=0.0, max_value=0.12)
spread = st.floats(min_value=0.0, max_value=0.02)


@st.composite
def pools(draw: st.DrawFn) -> Pool:
    ptr = draw(pass_through)
    return Pool(
        balance=draw(st.floats(min_value=1_000, max_value=1e9)),
        wac=ptr + draw(spread),
        wam=draw(st.integers(min_value=1, max_value=480)),
        pass_through_rate=ptr,
        wala=draw(st.integers(min_value=0, max_value=120)),
    )


models = st.one_of(
    st.builds(PSA, st.floats(min_value=0, max_value=1500)),
    st.builds(CPR, st.floats(min_value=0, max_value=1)),
)


@given(pools(), models)
def test_balance_never_negative_and_declines(pool, model):
    cf = project_cashflows(pool, model)
    assert (cf["ending_balance"] >= 0).all()
    assert (np.diff(cf["beginning_balance"]) <= 1e-9 * pool.balance).all()
    assert (
        (cf[["scheduled_principal", "prepayment", "net_interest", "servicing_fee"]] >= 0)
        .all()
        .all()
    )


@given(pools(), models)
def test_principal_sums_to_original_balance(pool, model):
    cf = project_cashflows(pool, model)
    assert cf["total_principal"].sum() == pytest.approx(pool.balance, rel=1e-9)
    assert cf["ending_balance"].iloc[-1] == pytest.approx(0.0, abs=1e-6 * pool.balance)


@given(pools(), models)
def test_cash_flow_identities(pool, model):
    cf = project_cashflows(pool, model)
    roll = cf["beginning_balance"] - cf["total_principal"] - cf["ending_balance"]
    assert np.abs(roll).max() <= 1e-7 * pool.balance
    split = cf["gross_interest"] - cf["net_interest"] - cf["servicing_fee"]
    assert np.abs(split).max() <= 1e-9 * pool.balance


@given(pools(), st.floats(0, 0.98), st.floats(0.005, 0.5))
def test_higher_cpr_gives_shorter_wal(pool, cpr, bump):
    slow = weighted_average_life(project_cashflows(pool, CPR(cpr))["total_principal"])
    fast = weighted_average_life(
        project_cashflows(pool, CPR(min(cpr + bump, 1.0)))["total_principal"]
    )
    if pool.wam == 1:
        assert fast == pytest.approx(slow)
    else:
        assert fast < slow


@given(pools(), st.floats(0, 800), st.floats(10, 500))
def test_higher_psa_gives_shorter_or_equal_wal(pool, speed, bump):
    slow = weighted_average_life(project_cashflows(pool, PSA(speed))["total_principal"])
    fast = weighted_average_life(project_cashflows(pool, PSA(speed + bump))["total_principal"])
    assert fast <= slow + 1e-12


@given(pools(), models, st.floats(-0.02, 0.25), st.floats(0.0001, 0.05))
def test_price_falls_when_yield_rises(pool, model, yld, bump):
    cf = project_cashflows(pool, model)
    low = price_from_yield(cf["cash_flow"], yld, pool.balance)
    high = price_from_yield(cf["cash_flow"], yld + bump, pool.balance)
    assert high < low


@given(pools(), models, st.floats(-0.02, 0.3))
def test_yield_from_price_inverts_price_from_yield(pool, model, yld):
    cf = project_cashflows(pool, model)
    price = price_from_yield(cf["cash_flow"], yld, pool.balance)
    assert yield_from_price(cf["cash_flow"], price, pool.balance) == pytest.approx(yld, abs=1e-9)


@st.composite
def tapes(draw: st.DrawFn) -> LoanTape:
    n = draw(st.integers(min_value=1, max_value=8))
    ptr = draw(pass_through)
    return LoanTape(
        balance=draw(st.lists(st.floats(1_000, 1e6), min_size=n, max_size=n)),
        note_rate=[ptr + s for s in draw(st.lists(spread, min_size=n, max_size=n))],
        remaining_term=draw(st.lists(st.integers(1, 360), min_size=n, max_size=n)),
        age=draw(st.lists(st.integers(0, 60), min_size=n, max_size=n)),
        pass_through_rate=ptr,
    )


@settings(max_examples=40, deadline=None)
@given(tapes(), models)
def test_vectorized_matches_naive_loop(tape, model):
    fast = project_cashflows(tape, model)
    slow = project_cashflows_naive(tape, model)
    scale = float(tape.balance.sum())
    for col in (
        "beginning_balance",
        "scheduled_principal",
        "prepayment",
        "ending_balance",
        "cash_flow",
    ):
        assert np.abs(fast[col].to_numpy() - slow[col].to_numpy()).max() <= 1e-8 * scale
