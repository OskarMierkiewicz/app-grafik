"""Wyświetlanie ról. Kod roli w raporcie (Kd, Kr, Kd/Kr) zostaje bez zmian, bo logika zamian i edycji sprawdza
"Kd"/"Kr" w tekście; użytkownik widzi nazwy i ikony. Konwersja tylko przy wyświetlaniu (działa też dla starszych grafików)."""
import re

ICONS = {"Kd/Kr": "🚑🩺", "Kd": "🚑", "Kr": "🩺"}
NAMES = {"Kd/Kr": "kierowca + kierownik", "Kd": "kierowca", "Kr": "kierownik"}
LEGEND = "🚑 kierowca   🩺 kierownik   🚑🩺 kierowca + kierownik"


def icon(code: str) -> str:
    return ICONS.get(code, "")


def name(code: str) -> str:
    return NAMES.get(code, code)


def full(code: str) -> str:
    """np. "kierowca + kierownik 🚑🩺"."""
    return f"{name(code)} {icon(code)}".strip()


def tags(text: str) -> str:
    """Zamienia znaczniki "[Kd/Kr]" w tekście (np. "Jan Kowalski [Kd/Kr]") na ikony."""
    return re.sub(r"\[(Kd/Kr|Kd|Kr)\]", lambda m: ICONS[m.group(1)], text or "")


def user_code(u) -> str:
    """Kod roli z użytkownika z bazy (can_drive / can_lead)."""
    if u.can_drive and u.can_lead:
        return "Kd/Kr"
    return "Kd" if u.can_drive else "Kr"
