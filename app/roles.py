"""Wyświetlanie ról. Kod roli w raporcie (Kd, Kr, Kd/Kr) zostaje bez zmian, bo logika zamian i edycji sprawdza
"Kd"/"Kr" w tekście; użytkownik widzi nazwy i ikony. Konwersja tylko przy wyświetlaniu (działa też dla starszych grafików)."""
import random
import re

from markupsafe import Markup, escape

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


# Wyświetlanie w HTML: czytelne znaczniki zamiast emoji (emoji zostają w Excelu i w listach rozwijanych).
BADGE_TEXT = {"Kd/Kr": "kierowca", "Kd": "tylko kierowca", "Kr": "kierownik"}
BADGE_CLASS = {"Kd/Kr": "kd", "Kd": "kdo", "Kr": "kr"}


def badge(code: str) -> Markup:
    """Mały znacznik roli. „kierowca” oznacza kierowcę, który jest też kierownikiem (domyślnie każdy nim jest)."""
    if code not in BADGE_TEXT:
        return Markup("")
    return Markup(f'<span class="rb {BADGE_CLASS[code]}" title="{escape(NAMES[code])}">{BADGE_TEXT[code]}</span>')


def _parse(item: str):
    m = re.fullmatch(r"(.*?)\s*\[(Kd/Kr|Kd|Kr)\]", item)
    return (m.group(1), m.group(2)) if m else (item, "")


def shift_roles(codes, key) -> list[str]:
    """Kto jest kim na zmianie: "d" (kierowca) albo "l" (kierownik) dla każdej z osób.

    Na pełnej zmianie jest jeden kierowca i jeden kierownik. Osoba z obiema uprawnieniami (Kd/Kr) dostaje rolę losowo,
    ale stabilnie (losowanie zależy od `key`, więc po odświeżeniu strony nic się nie zmienia). Gdy zmiana jest niepełna
    albo nie da się jej obsadzić poprawnie, role wynikają wprost z uprawnień."""
    can_d = [c in ("Kd", "Kd/Kr") for c in codes]
    can_l = [c in ("Kr", "Kd/Kr") for c in codes]
    if len(codes) == 2:
        options = []
        if can_d[0] and can_l[1]:
            options.append(["d", "l"])
        if can_d[1] and can_l[0]:
            options.append(["l", "d"])
        if options:
            return random.Random(str(key)).choice(options)
    return ["d" if (cd and not cl) or (cd and cl) else "l" for cd, cl in zip(can_d, can_l)]


def chips(people, seed=0, day=0, shift="") -> Markup:
    """Osoby ze zmiany jako chipy; kolor oznacza rolę na tej zmianie (niebieski kierowca, żółty kierownik), bez tekstu."""
    parsed = [_parse(x) for x in people or []]
    roles_ = shift_roles([c for _, c in parsed], (seed, day, shift))
    out = []
    for (name, _), r in zip(parsed, roles_):
        title = "kierowca" if r == "d" else "kierownik"
        out.append(f'<span class="pc {r}" title="{title}">{escape(name)}</span>')
    return Markup("".join(out))


def dot(code: str) -> Markup:
    """Kolorowa kropka przy nazwisku: niebieska kierowca, żółta tylko kierownik, zielona tylko kierowca (bez tekstu)."""
    if code not in BADGE_CLASS:
        return Markup("")
    return Markup(f'<span class="rd {BADGE_CLASS[code]}" title="{escape(NAMES[code])}"></span>')
