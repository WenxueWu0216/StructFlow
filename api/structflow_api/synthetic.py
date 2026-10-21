"""Deterministic synthetic loan tapes for demos, tests and benchmarks."""

from __future__ import annotations

import numpy as np
import pandas as pd

LOAN_LIMIT = 766_550.0  # 2024 conforming loan limit


def synthetic_tape(
    n_loans: int = 1_000, pass_through_rate: float = 0.055, seed: int = 7
) -> pd.DataFrame:
    """A plausible 30-year agency pool.

    Note rates sit 25-125 bp above the pass-through rate in 1/8 point steps,
    balances are lognormal around $300k capped at the conforming limit, and
    loans are 0-36 months seasoned on an original 360-month term.
    """
    rng = np.random.default_rng(seed)
    age = rng.integers(0, 37, n_loans)
    original = np.clip(rng.lognormal(np.log(300_000), 0.45, n_loans), 50_000, LOAN_LIMIT)
    # Scheduled paydown from seasoning, roughly 0.15% of balance per month of age.
    balance = np.round(original * (1 - 0.0015 * age), 2)
    note_rate = pass_through_rate + rng.integers(2, 11, n_loans) * 0.00125
    return pd.DataFrame(
        {
            "loan_id": [f"L{i:06d}" for i in range(1, n_loans + 1)],
            "balance": balance,
            "note_rate": np.round(note_rate, 5),
            "remaining_term": 360 - age,
            "age": age,
        }
    )
