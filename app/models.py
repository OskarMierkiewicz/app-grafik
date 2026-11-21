import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

DEFAULT_MIN_H = 96
DEFAULT_MAX_H = 192


class User(Base):
    """Osoba w systemie: rola i domyślne limity godzin."""
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("first_name", "last_name", name="uq_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    # Wartości domyślne są też w samej bazie (server_default), żeby dało się dodać osobę zwykłym
    # INSERT-em w Postgresie: wystarczy imię i nazwisko, kierowcę trzeba wskazać (can_drive = true).
    can_drive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # kierowca: trzeba wskazać
    can_lead: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # kierownik: każdy domyślnie
    min_h: Mapped[int] = mapped_column(Integer, default=DEFAULT_MIN_H, server_default=str(DEFAULT_MIN_H))  # domyślne min godzin
    max_h: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_H, server_default=str(DEFAULT_MAX_H))  # domyślne max godzin
    saldo: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # skumulowana uciążliwość
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # true = to jedyne miejsce pracy (limit ustawowy bez wpływu); false = pracuje też gdzie indziej
    only_job: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # dane logowania i kontaktu są w osobnej tabeli user_accounts (jedno konto na użytkownika)
    account: Mapped["UserAccount | None"] = relationship(back_populates="user", uselist=False,
                                                          cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class UserAccount(Base):
    """Konto logowania i kontakt użytkownika; połączone z users przez user_id."""
    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    login: Mapped[str] = mapped_column(String(80), unique=True)  # małe litery, np. "jan.kowalski"
    # hasło (pbkdf2$sól$hash); NULL = nie można się zalogować, dopóki administrator nie ustawi hasła
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # do kontaktu

    user: Mapped[User] = relationship(back_populates="account")


class Submission(Base):
    """Dyspozycja osoby na miesiąc (z pliku). min_h/max_h None = użyj domyślnych z users."""
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7), index=True)
    min_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    other_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # godziny pracy u innych pracodawców w tym miesiącu
    avail: Mapped[dict] = mapped_column(JSON)  # {"1": "D", "2": "DN", ...}
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    source: Mapped[str] = mapped_column(String(255), default="")

    user: Mapped[User] = relationship()


class Schedule(Base):
    """Wygenerowany grafik: raport JSON (do podglądu) i plik xlsx (do pobrania)."""
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    report: Mapped[dict] = mapped_column(JSON)
    xlsx: Mapped[bytes] = mapped_column(LargeBinary)
    saldo_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    # opublikowany grafik widzą wszyscy zalogowani użytkownicy (jeden na miesiąc); robocze tylko administrator
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Swap(Base):
    """Zamiana zmian w opublikowanym grafiku. Obie strony muszą zaakceptować (inicjator akceptuje przez złożenie prośby)."""
    __tablename__ = "swaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # A: oddaje give
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # B: przejmuje give
    give_day: Mapped[int] = mapped_column(Integer)
    give_shift: Mapped[str] = mapped_column(String(1))
    take_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # zmiana B oddawana A (None = samo przejęcie)
    take_shift: Mapped[str | None] = mapped_column(String(1), nullable=True)
    # pending | applied | rejected | cancelled | failed
    status: Mapped[str] = mapped_column(String(12), default="pending")
    by_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    partner: Mapped[User] = relationship(foreign_keys=[partner_id])


class ScheduleEdit(Base):
    """Dziennik ręcznych zmian administratora w grafiku (kto, kiedy, co i jakie ostrzeżenia)."""
    __tablename__ = "schedule_edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[int] = mapped_column(Integer)
    shift: Mapped[str] = mapped_column(String(1))
    action: Mapped[str] = mapped_column(String(6))  # add | remove
    note: Mapped[str] = mapped_column(String(1000), default="")  # ostrzeżenia w chwili zmiany
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    user: Mapped[User] = relationship()
