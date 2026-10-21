"""Prepayment models.

A prepayment model maps loan age (in months) to a single monthly mortality
(SMM): the fraction of the balance still outstanding after the scheduled
principal payment that prepays in that month.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray

PSA_RAMP_MONTHS = 30
PSA_TERMINAL_CPR = 0.06


def cpr_to_smm(cpr: ArrayLike) -> NDArray[np.float64]:
    """Convert an annual CPR to a monthly SMM: ``1 - (1 - CPR) ** (1/12)``."""
    cpr_arr = np.asarray(cpr, dtype=np.float64)
    if np.any((cpr_arr < 0) | (cpr_arr > 1)):
        raise ValueError("CPR must be between 0 and 1")
    return 1.0 - (1.0 - cpr_arr) ** (1.0 / 12.0)


def smm_to_cpr(smm: ArrayLike) -> NDArray[np.float64]:
    """Convert a monthly SMM to an annual CPR: ``1 - (1 - SMM) ** 12``."""
    smm_arr = np.asarray(smm, dtype=np.float64)
    if np.any((smm_arr < 0) | (smm_arr > 1)):
        raise ValueError("SMM must be between 0 and 1")
    return 1.0 - (1.0 - smm_arr) ** 12


class PrepayModel(Protocol):
    def cpr(self, age: ArrayLike) -> NDArray[np.float64]:
        """Annual CPR for loans of the given age in months (age 1 = first payment)."""
        ...

    def smm(self, age: ArrayLike) -> NDArray[np.float64]:
        """Monthly SMM for loans of the given age in months."""
        ...

    def describe(self) -> str: ...


@dataclass(frozen=True)
class CPR:
    """Constant prepayment rate, e.g. ``CPR(0.08)`` is 8% CPR at every age."""

    rate: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.rate <= 1.0:
            raise ValueError("CPR rate must be between 0 and 1")

    def cpr(self, age: ArrayLike) -> NDArray[np.float64]:
        return np.full(np.shape(age), self.rate, dtype=np.float64)

    def smm(self, age: ArrayLike) -> NDArray[np.float64]:
        return cpr_to_smm(self.cpr(age))

    def describe(self) -> str:
        return f"{self.rate * 100:g} CPR"


@dataclass(frozen=True)
class PSA:
    """Public Securities Association benchmark at ``speed`` percent.

    100 PSA: CPR is 0.2% in month 1, rises 0.2% per month to 6% at month 30,
    then stays at 6%. ``PSA(200)`` doubles every CPR in that ramp. CPR is
    capped at 100% for very high speeds.
    """

    speed: float

    def __post_init__(self) -> None:
        if self.speed < 0:
            raise ValueError("PSA speed must be non-negative")

    def cpr(self, age: ArrayLike) -> NDArray[np.float64]:
        age_arr = np.asarray(age, dtype=np.float64)
        if np.any(age_arr < 1):
            raise ValueError("loan age must be >= 1 month")
        base = PSA_TERMINAL_CPR * np.minimum(age_arr, PSA_RAMP_MONTHS) / PSA_RAMP_MONTHS
        return np.minimum(base * self.speed / 100.0, 1.0)

    def smm(self, age: ArrayLike) -> NDArray[np.float64]:
        return cpr_to_smm(self.cpr(age))

    def describe(self) -> str:
        return f"{self.speed:g} PSA"


def make_model(model: str, speed: float) -> PrepayModel:
    """Build a model from a name (``"PSA"`` or ``"CPR"``) and a speed.

    For CPR the speed is a percentage (``8`` means 8% CPR) so that both models
    take the same kind of number in the API and UI.
    """
    name = model.upper()
    if name == "PSA":
        return PSA(speed)
    if name == "CPR":
        return CPR(speed / 100.0)
    raise ValueError(f"unknown prepay model {model!r}; expected 'PSA' or 'CPR'")
