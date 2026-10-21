"""Request and response models. These are also the source of the OpenAPI document."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Rate = Annotated[float, Field(ge=0, lt=1, description="Annual rate as a decimal, 0.055 = 5.5%")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoanIn(Strict):
    loan_id: str = Field(min_length=1, max_length=64)
    balance: float = Field(gt=0, le=1e9, description="Current unpaid principal balance")
    note_rate: Rate
    remaining_term: int = Field(ge=1, le=480, description="Months remaining")
    age: int = Field(default=0, ge=0, le=480, description="Loan age in months (WALA input)")


class PoolCreate(Strict):
    name: str = Field(min_length=1, max_length=64)
    pass_through_rate: Rate
    loans: list[LoanIn] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def check_loans(self) -> Self:
        ids = [loan.loan_id for loan in self.loans]
        if len(set(ids)) != len(ids):
            raise ValueError("loan_id values must be unique within a pool")
        low = [loan.loan_id for loan in self.loans if loan.note_rate < self.pass_through_rate]
        if low:
            raise ValueError(
                f"note_rate is below pass_through_rate for loans: {', '.join(low[:5])}"
            )
        return self


class PoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pass_through_rate: float
    balance: float
    wac: float
    wam: int
    wala: int
    loan_count: int
    created_at: datetime


class PoolList(BaseModel):
    pools: list[PoolOut]


class Scenario(Strict):
    model: Literal["PSA", "CPR"] = Field(description="Prepayment model")
    speed: float = Field(
        ge=0,
        le=5000,
        description="PSA speed in percent (150 = 150% PSA), or CPR in percent (8 = 8% CPR)",
    )

    @model_validator(mode="after")
    def check_cpr(self) -> Self:
        if self.model == "CPR" and self.speed > 100:
            raise ValueError("CPR speed is a percentage and cannot exceed 100")
        return self


class CashFlowRow(BaseModel):
    month: int
    beginning_balance: float
    gross_interest: float
    servicing_fee: float
    net_interest: float
    scheduled_principal: float
    prepayment: float
    total_principal: float
    ending_balance: float
    cash_flow: float
    smm: float


class CashFlowResponse(BaseModel):
    pool_id: int
    scenario: Scenario
    wal: float = Field(description="Weighted average life in years")
    rows: list[CashFlowRow]


class PriceRequest(Scenario):
    yield_: float | None = Field(
        default=None,
        alias="yield",
        ge=-0.5,
        le=1,
        description="Annual yield, monthly compounding. Give exactly one of yield or price.",
    )
    price: float | None = Field(default=None, gt=0, le=500, description="Price per 100 face")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def one_of_yield_or_price(self) -> Self:
        if (self.yield_ is None) == (self.price is None):
            raise ValueError("give exactly one of 'yield' or 'price'")
        return self


class Analytics(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    price: float = Field(description="Price per 100 face")
    yield_: float = Field(alias="yield", description="Annual yield, monthly compounding")
    wal: float = Field(description="Weighted average life, years")
    modified_duration: float = Field(description="Static modified duration, years")
    convexity: float = Field(description="Static convexity, years squared")


class PriceResponse(Analytics):
    pool_id: int
    run_id: int
    scenario: Scenario


class ScenarioQuery(Strict):
    yield_: float | None = Field(default=None, alias="yield", ge=-0.5, le=1)
    price: float | None = Field(default=None, gt=0, le=500)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def at_most_one(self) -> Self:
        if self.yield_ is not None and self.price is not None:
            raise ValueError("give at most one of 'yield' or 'price'")
        return self


class ScenarioResult(Analytics):
    scenario: Scenario


class ScenarioResponse(BaseModel):
    pool_id: int
    basis: Literal["yield", "price"]
    value: float
    scenarios: list[ScenarioResult]


class ErrorDetail(BaseModel):
    loc: list[str | int] = []
    msg: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody
