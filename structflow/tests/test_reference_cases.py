"""Hand-checked reference cases. The arithmetic is written out in comments so a
reviewer can verify each expected number with a calculator."""

import numpy as np
import pytest

from structflow import (
    CPR,
    PSA,
    LoanTape,
    Pool,
    analytics_from_price,
    analytics_from_yield,
    convexity,
    cpr_to_smm,
    interpolate_rate,
    macaulay_duration,
    make_model,
    modified_duration,
    price_from_yield,
    project_cashflows,
    smm_to_cpr,
    weighted_average_life,
    yield_from_price,
)


def test_cpr_smm_conversion():
    # 6% CPR: SMM = 1 - (1 - 0.06) ** (1/12)
    #   ln(0.94) = -0.0618754; / 12 = -0.00515628; exp(...) = 0.99485699
    #   SMM = 1 - 0.99485699 = 0.00514301
    assert cpr_to_smm(0.06) == pytest.approx(0.00514301, abs=1e-8)
    assert smm_to_cpr(cpr_to_smm(0.06)) == pytest.approx(0.06)


def test_psa_ramp():
    # 100 PSA: CPR = 6% * min(age, 30) / 30 -> 0.2% at month 1, 3% at 15, 6% from 30 on.
    # 150 PSA multiplies each by 1.5.
    ages = np.array([1, 15, 30, 31, 360])
    assert PSA(100).cpr(ages) == pytest.approx([0.002, 0.03, 0.06, 0.06, 0.06])
    assert PSA(150).cpr(ages) == pytest.approx([0.003, 0.045, 0.09, 0.09, 0.09])
    # Speeds that would imply CPR > 100% are capped.
    assert PSA(2000).cpr([30]) == pytest.approx([1.0])


def test_zero_rate_straight_line_amortization():
    # 0% note rate, 12 months, 1,200 balance, no prepayment:
    #   level payment = 1,200 / 12 = 100 of principal per month, zero interest.
    # WAL = sum(t/12 * 100 for t in 1..12) / 1,200
    #     = (100 / 12) * (1 + 2 + ... + 12) / 1,200 = (100 / 12) * 78 / 1,200 = 0.541667 years
    cf = project_cashflows(Pool(balance=1200, wac=0.0, wam=12, pass_through_rate=0.0), CPR(0))
    assert cf["scheduled_principal"].to_numpy() == pytest.approx([100.0] * 12)
    assert cf["gross_interest"].sum() == pytest.approx(0.0)
    assert weighted_average_life(cf["total_principal"]) == pytest.approx(78 / 144)


def test_first_month_of_30_year_pool_at_100_psa():
    # Pool: 1,000,000 balance, 6.5% WAC, 360 WAM, 6.0% pass-through, brand new (WALA 0).
    # Monthly note rate r = 0.065 / 12 = 0.00541667
    # Level payment = B * r / (1 - (1 + r) ** -360)
    #   (1 + r) ** 360 = 6.991797; 1 - 1/6.991797 = 0.856975
    #   payment = 1,000,000 * 0.00541667 / 0.856975 = 6,320.68
    # Gross interest = 1,000,000 * 0.00541667 = 5,416.67
    # Scheduled principal = 6,320.68 - 5,416.67 = 904.01
    # Servicing + guarantee fee = 1,000,000 * (0.065 - 0.060) / 12 = 416.67
    # Net interest to investor = 1,000,000 * 0.06 / 12 = 5,000.00
    # Month-1 CPR at 100 PSA = 0.2%
    #   SMM = 1 - 0.998 ** (1/12): ln(0.998) / 12 = -0.000166834; exp(...) = 0.999833180
    #   SMM = 0.000166820
    # Prepayment = (1,000,000 - 904.01) * 0.000166820 = 999,095.99 * 0.000166820 = 166.67
    # Ending balance = 1,000,000 - 904.01 - 166.67 = 998,929.32
    pool = Pool(balance=1_000_000, wac=0.065, wam=360, pass_through_rate=0.06)
    m1 = project_cashflows(pool, PSA(100)).iloc[0]
    assert m1["gross_interest"] == pytest.approx(5416.67, abs=0.01)
    assert m1["scheduled_principal"] == pytest.approx(904.01, abs=0.01)
    assert m1["servicing_fee"] == pytest.approx(416.67, abs=0.01)
    assert m1["net_interest"] == pytest.approx(5000.00, abs=0.01)
    assert m1["prepayment"] == pytest.approx(166.67, abs=0.01)
    assert m1["ending_balance"] == pytest.approx(998_929.32, abs=0.01)
    assert m1["cash_flow"] == pytest.approx(5000.00 + 904.01 + 166.67, abs=0.02)


def test_one_month_pool_price_and_yield():
    # 100 face, 12% WAC = pass-through, 1 month left: the single cash flow is
    #   100 principal + 100 * 0.12 / 12 = 101.
    # At 12% yield: price = 101 / (1 + 0.12/12) = 101 / 1.01 = 100.00 (par)
    # At  6% yield: price = 101 / (1 + 0.06/12) = 101 / 1.005 = 100.497512
    cf = project_cashflows(Pool(balance=100, wac=0.12, wam=1, pass_through_rate=0.12), CPR(0))
    assert cf["cash_flow"].to_numpy() == pytest.approx([101.0])
    assert price_from_yield(cf["cash_flow"], 0.12, 100) == pytest.approx(100.0)
    assert price_from_yield(cf["cash_flow"], 0.06, 100) == pytest.approx(100.497512, abs=1e-6)
    assert yield_from_price(cf["cash_flow"], 100.497512, 100) == pytest.approx(0.06, abs=1e-6)


def test_bullet_duration_and_convexity():
    # Single cash flow of 100 at month 24, yield 6% (monthly rate 0.005).
    # Macaulay duration = 24 / 12 = 2 years.
    # Modified duration = 2 / 1.005 = 1.990050 years.
    # Convexity = t (t + 1) / 144 / (1 + y/12) ** 2 = 24 * 25 / 144 / 1.010025 = 4.125310
    flows = np.zeros(24)
    flows[-1] = 100.0
    assert macaulay_duration(flows, 0.06) == pytest.approx(2.0)
    assert modified_duration(flows, 0.06) == pytest.approx(1.990050, abs=1e-6)
    assert convexity(flows, 0.06) == pytest.approx(4.125310, abs=1e-6)


def test_pool_priced_at_its_coupon_is_par():
    # Discounting at the pass-through rate: each month's PV of (net interest + principal)
    # telescopes to the balance, so price = 100 for any prepayment speed.
    pool = Pool(balance=5_000_000, wac=0.0725, wam=354, pass_through_rate=0.065, wala=6)
    for model in (CPR(0), PSA(100), PSA(400), CPR(0.25)):
        res = analytics_from_yield(project_cashflows(pool, model), 0.065)
        assert res.price == pytest.approx(100.0, abs=1e-9)


def test_analytics_from_price_round_trip():
    cf = project_cashflows(Pool(1_000_000, 0.065, 360, 0.06), PSA(150))
    at_yield = analytics_from_yield(cf, 0.055)
    at_price = analytics_from_price(cf, at_yield.price)
    assert at_yield.price > 100  # discount rate below coupon -> premium
    assert at_price.yield_ == pytest.approx(0.055, abs=1e-10)
    assert at_price.modified_duration == pytest.approx(at_yield.modified_duration)
    assert set(at_price.to_dict()) == {"price", "yield", "wal", "modified_duration", "convexity"}


def test_loan_tape_summary_is_balance_weighted():
    # WAC = (100 * 6% + 300 * 7%) / 400 = (6 + 21) / 400 = 6.75%
    # WAM = (100 * 360 + 300 * 120) / 400 = (36,000 + 36,000) / 400 = 180
    tape = LoanTape([100, 300], [0.06, 0.07], [360, 120], [0, 4], pass_through_rate=0.055)
    s = tape.summary()
    assert (s.balance, s.wam, s.wala) == (400, 180, 3)
    assert s.wac == pytest.approx(0.0675)


def test_loan_level_projection_sums_individual_loans():
    tape = LoanTape([100_000, 250_000], [0.06, 0.07], [360, 240], [0, 12], pass_through_rate=0.055)
    whole = project_cashflows(tape, PSA(200))
    a = project_cashflows(Pool(100_000, 0.06, 360, 0.055, 0), PSA(200))
    b = project_cashflows(Pool(250_000, 0.07, 240, 0.055, 12), PSA(200))
    combined = a["total_principal"].to_numpy().copy()
    combined[:240] += b["total_principal"].to_numpy()
    assert whole["total_principal"].to_numpy() == pytest.approx(combined)


def test_curve_interpolation():
    # Halfway between 2y at 4% and 5y at 4.6%: at 3.5y -> 4% + 0.5 * 0.6% = 4.3%
    assert interpolate_rate([2, 5, 10], [0.04, 0.046, 0.05], 3.5) == pytest.approx(0.043)
    assert interpolate_rate([2, 5, 10], [0.04, 0.046, 0.05], 30) == pytest.approx(0.05)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"balance": -1, "wac": 0.06, "wam": 360, "pass_through_rate": 0.05},
        {"balance": 1, "wac": 0.06, "wam": 0, "pass_through_rate": 0.05},
        {"balance": 1, "wac": 0.04, "wam": 360, "pass_through_rate": 0.05},
        {"balance": 1, "wac": 0.06, "wam": 360, "pass_through_rate": 0.05, "wala": -1},
    ],
)
def test_invalid_pools_rejected(kwargs):
    with pytest.raises(ValueError):
        Pool(**kwargs)


def test_invalid_models_and_prices_rejected():
    with pytest.raises(ValueError):
        PSA(-1)
    with pytest.raises(ValueError):
        CPR(1.5)
    with pytest.raises(ValueError):
        make_model("ABS", 1)
    with pytest.raises(ValueError):
        yield_from_price([1.0, 101.0], -5, 100)
    assert make_model("cpr", 8) == CPR(0.08)
