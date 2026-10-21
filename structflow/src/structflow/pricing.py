"""Price, yield and risk measures for a projected cash flow stream.

Conventions (kept deliberately simple; see docs/domain.md):

* Yields are annual rates compounded monthly ("mortgage yield"). Cash flow
  for month ``t`` is discounted by ``(1 + y/12) ** t``.
* Settlement is on a payment date, so there is no accrued interest and no
  payment delay; price is clean = dirty.
* Price is quoted per 100 of current face (the pool balance at settlement).
* Duration and convexity are static: cash flows are held fixed as the yield
  moves, i.e. prepayment speeds do not react to rates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

YIELD_FLOOR = -0.99  # keeps (1 + y/12) comfortably positive
YIELD_CEILING = 10.0


def _validate_flows(cash_flows: ArrayLike) -> NDArray[np.float64]:
    cf = np.asarray(cash_flows, dtype=np.float64)
    if cf.ndim != 1 or cf.size == 0:
        raise ValueError("cash flows must be a non-empty 1-D array")
    if not np.all(np.isfinite(cf)) or np.any(cf < 0):
        raise ValueError("cash flows must be finite and non-negative")
    if cf.sum() <= 0:
        raise ValueError("cash flows must not all be zero")
    return cf


def _discount_factors(n: int, yld: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    if not YIELD_FLOOR <= yld <= YIELD_CEILING:
        raise ValueError(f"yield must be between {YIELD_FLOOR} and {YIELD_CEILING}")
    t = np.arange(1, n + 1, dtype=np.float64)
    return t, (1.0 + yld / 12.0) ** -t


def price_from_yield(cash_flows: ArrayLike, yld: float, face: float) -> float:
    """Price per 100 face of monthly ``cash_flows`` discounted at ``yld``."""
    if face <= 0:
        raise ValueError("face must be positive")
    cf = _validate_flows(cash_flows)
    _, df = _discount_factors(cf.size, yld)
    return float(100.0 * np.dot(cf, df) / face)


def yield_from_price(
    cash_flows: ArrayLike, price: float, face: float, tol: float = 1e-12, max_iter: int = 200
) -> float:
    """Yield that reprices ``cash_flows`` to ``price`` (per 100 face).

    Price is strictly decreasing in yield for non-negative cash flows, so the
    root is unique. Newton steps are used while they stay inside a shrinking
    bisection bracket; otherwise the method falls back to bisection, which
    guarantees convergence.
    """
    if not np.isfinite(price) or price <= 0:
        raise ValueError("price must be positive")
    cf = _validate_flows(cash_flows)
    lo, hi = YIELD_FLOOR, YIELD_CEILING

    def f(y: float) -> tuple[float, float]:
        t, df = _discount_factors(cf.size, y)
        pv = 100.0 * np.dot(cf, df) / face
        dpv = -100.0 * np.dot(cf * t / 12.0, df) / (1.0 + y / 12.0) / face
        return float(pv - price), float(dpv)

    f_lo, _ = f(lo)
    f_hi, _ = f(hi)
    if f_lo < 0 or f_hi > 0:
        raise ValueError(f"price {price} is outside the range reachable for yields in [{lo}, {hi}]")

    y = 0.05
    for _ in range(max_iter):
        fy, dfy = f(y)
        if abs(fy) < 1e-13 * max(price, 1.0):
            return y
        if fy > 0:
            lo = y
        else:
            hi = y
        step = fy / dfy if dfy != 0 else np.inf
        y_new = y - step
        if not lo < y_new < hi:
            y_new = 0.5 * (lo + hi)
        if abs(y_new - y) < tol:
            return float(y_new)
        y = float(y_new)
    raise RuntimeError("yield solver did not converge")


def weighted_average_life(principal: ArrayLike) -> float:
    """WAL in years: sum(t/12 * principal_t) / sum(principal_t)."""
    p = np.asarray(principal, dtype=np.float64)
    total = p.sum()
    if total <= 0:
        raise ValueError("principal must sum to a positive amount")
    t = np.arange(1, p.size + 1, dtype=np.float64)
    return float(np.dot(t / 12.0, p) / total)


def macaulay_duration(cash_flows: ArrayLike, yld: float) -> float:
    """PV-weighted average time to cash flow, in years."""
    cf = _validate_flows(cash_flows)
    t, df = _discount_factors(cf.size, yld)
    pv = cf * df
    return float(np.dot(t / 12.0, pv) / pv.sum())


def modified_duration(cash_flows: ArrayLike, yld: float) -> float:
    """-(1/P) dP/dy = Macaulay duration / (1 + y/12)."""
    return macaulay_duration(cash_flows, yld) / (1.0 + yld / 12.0)


def convexity(cash_flows: ArrayLike, yld: float) -> float:
    """(1/P) d2P/dy2 = sum(t(t+1)/144 * PV_t) / (P * (1 + y/12)**2), in years squared."""
    cf = _validate_flows(cash_flows)
    t, df = _discount_factors(cf.size, yld)
    pv = cf * df
    return float(np.dot(t * (t + 1.0) / 144.0, pv) / (pv.sum() * (1.0 + yld / 12.0) ** 2))


@dataclass(frozen=True)
class PricingResult:
    price: float
    yield_: float
    wal: float
    modified_duration: float
    convexity: float

    def to_dict(self) -> dict[str, float]:
        d = asdict(self)
        d["yield"] = d.pop("yield_")
        return d


def _flows(cf: pd.DataFrame) -> tuple[NDArray[np.float64], float]:
    return cf["cash_flow"].to_numpy(dtype=np.float64), float(cf["beginning_balance"].iloc[0])


def analytics_from_yield(cf: pd.DataFrame, yld: float) -> PricingResult:
    """All measures for a projected cash flow frame priced at ``yld``."""
    flows, face = _flows(cf)
    return PricingResult(
        price=price_from_yield(flows, yld, face),
        yield_=yld,
        wal=weighted_average_life(cf["total_principal"].to_numpy()),
        modified_duration=modified_duration(flows, yld),
        convexity=convexity(flows, yld),
    )


def analytics_from_price(cf: pd.DataFrame, price: float) -> PricingResult:
    """All measures for a projected cash flow frame bought at ``price``."""
    flows, face = _flows(cf)
    yld = yield_from_price(flows, price, face)
    return PricingResult(
        price=price,
        yield_=yld,
        wal=weighted_average_life(cf["total_principal"].to_numpy()),
        modified_duration=modified_duration(flows, yld),
        convexity=convexity(flows, yld),
    )
