"""Rate curve helpers."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def interpolate_rate(tenors: ArrayLike, rates: ArrayLike, tenor: float) -> float:
    """Linear interpolation on a par curve, flat beyond the first and last points.

    ``tenors`` are in years and must be strictly increasing.
    """
    x = np.asarray(tenors, dtype=np.float64)
    y = np.asarray(rates, dtype=np.float64)
    if x.ndim != 1 or x.shape != y.shape or x.size == 0:
        raise ValueError("tenors and rates must be non-empty 1-D arrays of equal length")
    if np.any(np.diff(x) <= 0):
        raise ValueError("tenors must be strictly increasing")
    return float(np.interp(tenor, x, y))
