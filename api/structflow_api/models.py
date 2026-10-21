"""SQLAlchemy models. Schema changes go through Alembic (migrations/)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    pass_through_rate: Mapped[float] = mapped_column(Float)
    # Balance-weighted summary, stored at ingestion so listings need no loan scan.
    balance: Mapped[float] = mapped_column(Float)
    wac: Mapped[float] = mapped_column(Float)
    wam: Mapped[int] = mapped_column(Integer)
    wala: Mapped[int] = mapped_column(Integer)
    loan_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loans: Mapped[list[Loan]] = relationship(
        back_populates="pool", cascade="all, delete-orphan", passive_deletes=True
    )


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (UniqueConstraint("pool_id", "loan_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), index=True)
    loan_id: Mapped[str] = mapped_column(String(64))
    balance: Mapped[float] = mapped_column(Float)
    note_rate: Mapped[float] = mapped_column(Float)
    remaining_term: Mapped[int] = mapped_column(Integer)
    age: Mapped[int] = mapped_column(Integer)

    pool: Mapped[Pool] = relationship(back_populates="loans")


class RateCurve(Base):
    __tablename__ = "rate_curves"
    __table_args__ = (UniqueConstraint("name", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[date] = mapped_column(Date)

    points: Mapped[list[RateCurvePoint]] = relationship(
        back_populates="curve",
        cascade="all, delete-orphan",
        order_by="RateCurvePoint.tenor_years",
    )


class RateCurvePoint(Base):
    __tablename__ = "rate_curve_points"
    __table_args__ = (UniqueConstraint("curve_id", "tenor_years"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    curve_id: Mapped[int] = mapped_column(ForeignKey("rate_curves.id", ondelete="CASCADE"))
    tenor_years: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)

    curve: Mapped[RateCurve] = relationship(back_populates="points")


class Run(Base):
    """One analytics calculation: an API price request or a batch reprice."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "price" or "batch"
    as_of: Mapped[date | None] = mapped_column(Date, index=True)
    curve_id: Mapped[int | None] = mapped_column(ForeignKey("rate_curves.id", ondelete="SET NULL"))
    prepay_model: Mapped[str] = mapped_column(String(8))
    speed: Mapped[float] = mapped_column(Float)
    library_version: Mapped[str] = mapped_column(String(16))
    inputs: Mapped[dict[str, float]] = mapped_column(JSON)
    price: Mapped[float] = mapped_column(Float)
    yield_: Mapped[float] = mapped_column("yield", Float)
    wal: Mapped[float] = mapped_column(Float)
    modified_duration: Mapped[float] = mapped_column(Float)
    convexity: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
