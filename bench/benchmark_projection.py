"""Time loan-level cash flow projection: vectorized NumPy vs a naive Python loop.

    python bench/benchmark_projection.py            # 10,000 loans
    python bench/benchmark_projection.py --loans 500 --repeat 1

Both implementations live in structflow.cashflows; the script also checks
they agree before reporting the speedup.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

import numpy as np
import pandas as pd

from structflow import PSA, LoanTape, project_cashflows, project_cashflows_naive


def synthetic_tape(n: int, seed: int = 11) -> LoanTape:
    rng = np.random.default_rng(seed)
    age = rng.integers(0, 37, n)
    return LoanTape(
        balance=np.clip(rng.lognormal(np.log(300_000), 0.45, n), 50_000, 766_550),
        note_rate=0.055 + rng.integers(2, 11, n) * 0.00125,
        remaining_term=360 - age,
        age=age,
        pass_through_rate=0.055,
    )


def best_time(fn: Callable[[], pd.DataFrame], repeat: int) -> tuple[float, pd.DataFrame]:
    best, result = float("inf"), None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        best = min(best, time.perf_counter() - start)
    assert result is not None
    return best, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loans", type=int, default=10_000)
    parser.add_argument("--repeat", type=int, default=3, help="runs per method; best is reported")
    args = parser.parse_args()

    tape = synthetic_tape(args.loans)
    model = PSA(150)
    horizon = int(tape.remaining_term.max())
    print(f"pool: {args.loans:,} loans, {horizon} months, {model.describe()}")

    t_vec, fast = best_time(lambda: project_cashflows(tape, model), args.repeat)
    t_loop, slow = best_time(lambda: project_cashflows_naive(tape, model), args.repeat)

    worst = float(np.max(np.abs(fast["cash_flow"].to_numpy() - slow["cash_flow"].to_numpy())))
    rel = worst / float(tape.balance.sum())
    if rel > 1e-9:
        raise SystemExit(f"implementations disagree: max cash flow difference {worst:.6g}")

    print(f"vectorized (NumPy):   {t_vec * 1000:10.1f} ms")
    print(f"naive loop (Python):  {t_loop * 1000:10.1f} ms")
    print(f"speedup:              {t_loop / t_vec:10.1f}x")
    print(f"max cash flow difference: {worst:.3g} (relative to pool balance {rel:.1e})")


if __name__ == "__main__":
    main()
