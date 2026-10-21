"""Monthly cash flow projection for a pass-through pool.

The vectorized projection uses a closed form. For a level-payment loan with
monthly note rate ``r`` and ``N`` months remaining, the scheduled balance as a
fraction of today's balance after ``t`` payments is::

    S_t = (1 - v**(N - t)) / (1 - v**N),   v = 1 / (1 + r)     (S_t = 1 - t/N if r == 0)

Prepayments do not change that shape: after a prepayment the borrower's
payment is recast over the same remaining term, so the remaining balance keeps
amortizing along the same curve. With survival factor
``Q_t = prod_{i<=t} (1 - SMM_i)`` the actual balance is therefore
``B_t = B_0 * S_t * Q_t`` and each month's flows follow directly:

    scheduled principal_t = B_0 * Q_{t-1} * (S_{t-1} - S_t)
    prepayment_t          = B_0 * Q_{t-1} * S_t * SMM_t

That turns the month-by-month recursion into array arithmetic over a
(loans x months) grid. ``project_cashflows_naive`` runs the textbook loop
instead and exists as an independent check and a benchmark baseline.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from structflow.pool import LoanTape, Pool
from structflow.prepay import PrepayModel

COLUMNS = [
    "month",
    "beginning_balance",
    "gross_interest",
    "servicing_fee",
    "net_interest",
    "scheduled_principal",
    "prepayment",
    "total_principal",
    "ending_balance",
    "cash_flow",
    "smm",
]

# Loans projected per block; keeps each (loans x months) array near 6 MB for a 360-month horizon.
_CHUNK = 2_000


def _as_tape(pool: Pool | LoanTape) -> LoanTape:
    return pool.to_tape() if isinstance(pool, Pool) else pool


def _schedule_factor(
    monthly_rate: NDArray[np.float64], term: NDArray[np.int64], t: NDArray[np.int64]
) -> NDArray[np.float64]:
    """S_t for each loan (rows) and month index t (columns, starting at 0)."""
    remaining = np.maximum(term - t, 0).astype(np.float64)
    n = term.astype(np.float64)
    zero = monthly_rate <= 0
    log_v = -np.log1p(np.where(zero, 1.0, monthly_rate))
    factor: NDArray[np.float64] = np.expm1(remaining * log_v) / np.expm1(n * log_v)
    if zero.any():
        factor = np.where(zero, remaining / n, factor)
    return factor


def project_cashflows(pool: Pool | LoanTape, model: PrepayModel) -> pd.DataFrame:
    """Project monthly pool cash flows under a prepayment model.

    Returns one row per month (``month`` starts at 1) with the columns in
    ``COLUMNS``. ``cash_flow`` is what the investor receives: net interest at
    the pass-through rate plus all principal. ``smm`` is the pool-level
    effective SMM (prepayment over balance after scheduled principal).
    """
    tape = _as_tape(pool)
    horizon = int(np.max(tape.remaining_term))
    months = np.arange(horizon + 1)
    # SMM depends only on loan age, so evaluate the model once per age and index into it.
    smm_by_age = np.concatenate(
        ([0.0], model.smm(np.arange(1, int(np.max(tape.age)) + horizon + 1)))
    )
    sums = {k: np.zeros(horizon) for k in ("beg", "fee", "sched", "prepay")}

    for start in range(0, len(tape), _CHUNK):
        sl = slice(start, start + _CHUNK)
        b0 = tape.balance[sl]
        fee_rate = (tape.note_rate[sl] - tape.pass_through_rate) / 12.0

        # Grids are (loans, months). S has horizon + 1 columns with S_0 = 1.
        s = _schedule_factor(tape.note_rate[sl, None] / 12.0, tape.remaining_term[sl, None], months)
        smm = smm_by_age[tape.age[sl, None] + months[1:]]
        # Survival to the start of each month. Months past a loan's term need no
        # masking: S is zero there, so every flow below is zero too.
        q_prev = np.ones_like(smm)
        np.cumprod(1.0 - smm[:, :-1], axis=1, out=q_prev[:, 1:])

        # Per unit of original balance: balance at the start of the month, and the
        # balance left after scheduled principal but before prepayment.
        live = s[:, :-1] * q_prev
        after_sched = s[:, 1:] * q_prev
        # Summing over loans weighted by balance is a matrix-vector product.
        beg = b0 @ live
        sums["beg"] += beg
        sums["fee"] += (b0 * fee_rate) @ live
        sums["sched"] += beg - b0 @ after_sched
        sums["prepay"] += b0 @ (after_sched * smm)

    # A month's ending balance is the next month's beginning balance; the pool is
    # fully paid down after the longest loan's last payment.
    sums["end"] = np.append(sums["beg"][1:], 0.0)
    return _frame(sums, tape.pass_through_rate)


def project_cashflows_naive(pool: Pool | LoanTape, model: PrepayModel) -> pd.DataFrame:
    """Reference implementation: loop over every loan and every month."""
    tape = _as_tape(pool)
    horizon = int(np.max(tape.remaining_term))
    beg_s = [0.0] * horizon
    fee_s = [0.0] * horizon
    sched_s = [0.0] * horizon
    prepay_s = [0.0] * horizon
    end_s = [0.0] * horizon
    # SMM by loan age, looked up per month so the loop does no NumPy calls.
    max_age = int(np.max(tape.age)) + horizon
    smm_by_age = [0.0, *model.smm(np.arange(1, max_age + 1)).tolist()]

    for i in range(len(tape)):
        balance = float(tape.balance[i])
        r = float(tape.note_rate[i]) / 12.0
        fee_rate = (float(tape.note_rate[i]) - tape.pass_through_rate) / 12.0
        term = int(tape.remaining_term[i])
        age = int(tape.age[i])
        for t in range(1, term + 1):
            remaining = term - t + 1
            interest = balance * r
            if r > 0:
                # balance * r / (1 - (1 + r) ** -remaining), written to stay exact for tiny r
                payment = balance * r / -math.expm1(-remaining * math.log1p(r))
            else:
                payment = balance / remaining
            sched = min(payment - interest, balance)
            smm = smm_by_age[age + t]
            prepay = (balance - sched) * smm
            end = balance - sched - prepay
            beg_s[t - 1] += balance
            fee_s[t - 1] += balance * fee_rate
            sched_s[t - 1] += sched
            prepay_s[t - 1] += prepay
            end_s[t - 1] += end
            balance = end

    sums = {
        "beg": np.array(beg_s),
        "fee": np.array(fee_s),
        "sched": np.array(sched_s),
        "prepay": np.array(prepay_s),
        "end": np.array(end_s),
    }
    return _frame(sums, tape.pass_through_rate)


def _frame(sums: dict[str, NDArray[np.float64]], pass_through_rate: float) -> pd.DataFrame:
    beg = sums["beg"]
    # Tiny negative values can only come from floating-point cancellation.
    end = np.maximum(sums["end"], 0.0)
    net = beg * pass_through_rate / 12.0
    fee = np.maximum(sums["fee"], 0.0)
    principal = sums["sched"] + sums["prepay"]
    after_sched = beg - sums["sched"]
    with np.errstate(divide="ignore", invalid="ignore"):
        smm = np.where(after_sched > 0, sums["prepay"] / after_sched, 0.0)
    return pd.DataFrame(
        {
            "month": np.arange(1, beg.size + 1),
            "beginning_balance": beg,
            "gross_interest": net + fee,
            "servicing_fee": fee,
            "net_interest": net,
            "scheduled_principal": sums["sched"],
            "prepayment": sums["prepay"],
            "total_principal": principal,
            "ending_balance": end,
            "cash_flow": net + principal,
            "smm": smm,
        },
        columns=COLUMNS,
    )
