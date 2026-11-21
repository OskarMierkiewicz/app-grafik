"""Terminy składania dyspozycji.

Dyspozycję na miesiąc M można składać i podmieniać do SUBMISSION_DEADLINE_DAY (domyślnie 10.)
dnia miesiąca poprzedzającego M (włącznie). Od następnego dnia (11.) jest blokada.
Blokada działa też wcześniej, gdy administrator już wygenerował grafik na miesiąc M.
Administrator nie podlega blokadzie.
"""
import calendar
import datetime as dt
import os
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Schedule
from .solver import parse_month


def today() -> dt.date:
    return dt.datetime.now(ZoneInfo(os.getenv("TZ_NAME", "Europe/Warsaw"))).date()


def deadline_day() -> int:
    return int(os.getenv("SUBMISSION_DEADLINE_DAY", "10"))


def deadline_for(month: str) -> dt.date:
    y, m = parse_month(month)
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return dt.date(py, pm, min(deadline_day(), calendar.monthrange(py, pm)[1]))  # np. 31 w listopadzie → 30


def lock_reason(db: Session, month: str, on: dt.date | None = None) -> str | None:
    """Powód blokady składania dyspozycji na `month` albo None, gdy można je składać."""
    on = on or today()
    if db.scalar(select(Schedule.id).where(Schedule.month == month).limit(1)):
        return f"grafik na {month} został już wygenerowany przez administratora"
    dl = deadline_for(month)
    if on > dl:
        return f"termin minął ({dl.strftime('%d.%m.%Y')} włącznie); od {(dl + dt.timedelta(days=1)).strftime('%d.%m.%Y')} dyspozycji nie można zmieniać"
    return None


def open_month() -> str:
    """Miesiąc, na który zapisy są teraz otwarte: do SUBMISSION_DEADLINE_DAY następny miesiąc, potem kolejny po nim."""
    t = today()
    idx = t.year * 12 + (t.month - 1) + (1 if t.day <= deadline_day() else 2)
    return f"{idx // 12}-{idx % 12 + 1:02d}"
