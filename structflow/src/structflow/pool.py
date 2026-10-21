"""Pool and loan tape inputs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class Pool:
    """Representative-line description of a pass-through pool.

    Rates are annual decimals (``0.065`` = 6.5%). ``wam`` is the remaining term
    in months and ``wala`` the loan age in months, which drives the PSA ramp.
    """

    balance: float
    wac: float
    wam: int
    pass_through_rate: float
    wala: int = 0

    def __post_init__(self) -> None:
        _validate(
            np.array([self.balance]),
            np.array([self.wac]),
            np.array([self.wam]),
            np.array([self.wala]),
            self.pass_through_rate,
        )

    def to_tape(self) -> LoanTape:
        return LoanTape(
            balance=[self.balance],
            note_rate=[self.wac],
            remaining_term=[self.wam],
            age=[self.wala],
            pass_through_rate=self.pass_through_rate,
        )


@dataclass(frozen=True, eq=False, init=False)
class LoanTape:
    """Loan-level pool data: one array entry per loan.

    Every loan pays investors the pool's single ``pass_through_rate``; the gap
    between each loan's note rate and that rate is the servicing and guarantee
    fee strip.
    """

    balance: NDArray[np.float64]
    note_rate: NDArray[np.float64]
    remaining_term: NDArray[np.int64]
    age: NDArray[np.int64]
    pass_through_rate: float

    def __init__(
        self,
        balance: ArrayLike,
        note_rate: ArrayLike,
        remaining_term: ArrayLike,
        age: ArrayLike | None = None,
        pass_through_rate: float = 0.0,
    ) -> None:
        bal = np.atleast_1d(np.asarray(balance, dtype=np.float64))
        rate = np.atleast_1d(np.asarray(note_rate, dtype=np.float64))
        term_f = np.atleast_1d(np.asarray(remaining_term, dtype=np.float64))
        age_f = (
            np.zeros_like(bal) if age is None else np.atleast_1d(np.asarray(age, dtype=np.float64))
        )
        if not (bal.shape == rate.shape == term_f.shape == age_f.shape) or bal.ndim != 1:
            raise ValueError("loan tape columns must be 1-D arrays of equal length")
        if bal.size == 0:
            raise ValueError("loan tape must contain at least one loan")
        if np.any(term_f != np.round(term_f)) or np.any(age_f != np.round(age_f)):
            raise ValueError("remaining_term and age must be whole months")
        term = term_f.astype(np.int64)
        loan_age = age_f.astype(np.int64)
        _validate(bal, rate, term, loan_age, pass_through_rate)
        object.__setattr__(self, "balance", bal)
        object.__setattr__(self, "note_rate", rate)
        object.__setattr__(self, "remaining_term", term)
        object.__setattr__(self, "age", loan_age)
        object.__setattr__(self, "pass_through_rate", float(pass_through_rate))

    def __len__(self) -> int:
        return int(self.balance.size)

    def summary(self) -> Pool:
        """Balance-weighted WAC / WAM / WALA representative line."""
        total = float(self.balance.sum())
        w = self.balance / total
        return Pool(
            balance=total,
            wac=float(np.dot(w, self.note_rate)),
            wam=round(float(np.dot(w, self.remaining_term))),
            pass_through_rate=self.pass_through_rate,
            wala=round(float(np.dot(w, self.age))),
        )


def _validate(
    balance: NDArray[np.float64],
    note_rate: NDArray[np.float64],
    remaining_term: NDArray[np.int64],
    age: NDArray[np.int64],
    pass_through_rate: float,
) -> None:
    if not np.all(np.isfinite(balance)) or np.any(balance <= 0):
        raise ValueError("balance must be positive and finite")
    if not np.all(np.isfinite(note_rate)) or np.any((note_rate < 0) | (note_rate >= 1)):
        raise ValueError("note rate / WAC must be in [0, 1)")
    if np.any((remaining_term < 1) | (remaining_term > 600)):
        raise ValueError("remaining term must be between 1 and 600 months")
    if np.any(age < 0):
        raise ValueError("loan age must be non-negative")
    if not 0 <= pass_through_rate < 1:
        raise ValueError("pass-through rate must be in [0, 1)")
    if np.any(note_rate < pass_through_rate - 1e-12):
        raise ValueError("note rate / WAC must be at least the pass-through rate")
