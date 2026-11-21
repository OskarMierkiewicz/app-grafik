"""Limit łącznego czasu pracy medyków pracujących u kilku świadczeniodawców.

Podstawa: nowelizacja ustawy o świadczeniach opieki zdrowotnej finansowanych ze środków
publicznych (Sejm przyjął poprawki Senatu 19.11.2026; ustawa czeka na podpis prezydenta).
Wg doniesień prasowych (Rynek Zdrowia, 20.11.2026): łączny czas pracy medyka w publicznym
systemie nie może przekroczyć 320 h, czyli 2 etatów (160 h na etat), dla UoP i umów
cywilnoprawnych; dotyczy lekarzy, pielęgniarek, położnych, fizjoterapeutów i ratowników.

UWAGA: szczegóły (czy 320 h jest miesięczne, jak liczyć dyżury, czy objęte są ZRM) nie są
potwierdzone w tekście ustawy. Dlatego wszystko jest konfigurowalne zmiennymi środowiskowymi:

  LAW_ENABLED=1            wyłącz (0), jeśli ustawa nie wejdzie w życie
  LAW_EFFECTIVE_FROM=2027-01   pierwszy miesiąc grafiku, od którego limit obowiązuje
  LAW_TOTAL_MAX_H=320      limit łączny godzin u wszystkich pracodawców w miesiącu
"""
import os


def _enabled():
    return os.getenv("LAW_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")


def total_max_h() -> int:
    return int(os.getenv("LAW_TOTAL_MAX_H", "320"))


def effective_from() -> str:
    return os.getenv("LAW_EFFECTIVE_FROM", "2027-01")


def law_active(month: str) -> bool:
    """month: 'RRRR-MM'. Porównanie tekstowe działa dla tego formatu."""
    return _enabled() and month >= effective_from()


def apply_limit(month: str, only_job: bool, other_hours: int | None, max_h: int, min_h: int):
    """Zwraca (min_h, max_h, notatka) po uwzględnieniu limitu ustawowego.

    only_job=True: bez zmian. only_job=False: max h = min(max h, limit − godziny gdzie indziej).
    Gdy limit zejdzie poniżej minimum, minimum jest obniżane (ustawa ma pierwszeństwo).
    """
    if only_job or not law_active(month):
        return min_h, max_h, ""
    if other_hours is None:
        raise ValueError("brak godzin w innych miejscach")
    room = max(0, total_max_h() - other_hours)
    if room >= max_h:
        return min_h, max_h, ""
    note = f"limit ustawowy: max {room} h ({total_max_h()} − {other_hours} h w innych miejscach)"
    return min(min_h, room), room, note
