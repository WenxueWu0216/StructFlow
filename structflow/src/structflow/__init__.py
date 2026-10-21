"""StructFlow: agency MBS pass-through cash flow and pricing library."""

from structflow.cashflows import COLUMNS, project_cashflows, project_cashflows_naive
from structflow.curve import interpolate_rate
from structflow.pool import LoanTape, Pool
from structflow.prepay import CPR, PSA, PrepayModel, cpr_to_smm, make_model, smm_to_cpr
from structflow.pricing import (
    PricingResult,
    analytics_from_price,
    analytics_from_yield,
    convexity,
    macaulay_duration,
    modified_duration,
    price_from_yield,
    weighted_average_life,
    yield_from_price,
)

__version__ = "0.1.0"

__all__ = [
    "COLUMNS",
    "CPR",
    "PSA",
    "LoanTape",
    "Pool",
    "PrepayModel",
    "PricingResult",
    "analytics_from_price",
    "analytics_from_yield",
    "convexity",
    "cpr_to_smm",
    "interpolate_rate",
    "macaulay_duration",
    "make_model",
    "modified_duration",
    "price_from_yield",
    "project_cashflows",
    "project_cashflows_naive",
    "smm_to_cpr",
    "weighted_average_life",
    "yield_from_price",
]
