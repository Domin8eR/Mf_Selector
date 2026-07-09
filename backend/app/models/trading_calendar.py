from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class TradingCalendar(Base):
    """
    One row per calendar date; is_trading_day = False for weekends and
    Indian public holidays. Every NAV query must INNER JOIN this table
    so we never process weekend rows or artificially repeated NAVs.
    """

    __tablename__ = "trading_calendar"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="NSE_FO")
