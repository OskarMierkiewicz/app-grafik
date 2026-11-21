"""Zamiany zmian między pracownikami w opublikowanym grafiku.

Zamiana: A oddaje zmianę (dzień, D/N), B oddaje zmianę w zamian (opcjonalnie; bez niej B tylko przejmuje).
Twarde warunki po zamianie (dla użytkownika i administratora):
  - na zmianie max 2 osoby, a jeśli 2 osoby: jedna prowadzi, druga jest kierownikiem (nie para kierowca+kierowca
    bez kierownika ani kierownik+kierownik);
  - osoba nie dostaje zmiany, którą już ma;
  - godziny osoby po zmianie <= jej max h (w tym limit ustawowy).
"""
import copy
import datetime as dt

from .solver import HOURS, PER_SHIFT, parse_month, recompute_report

SHIFT_NAMES = {"D": "dzień 7-19", "N": "noc 19-7"}
WD = ["pn", "wt", "śr", "cz", "pt", "so", "nd"]


class SwapError(Exception):
    pass


def person(rep, uid):
    return next((p for p in rep["people"] if p["uid"] == uid), None)


def holds(p, day, shift):
    return shift in p["assign"].get(str(day), "")


def _toggle(p, day, shift, on):
    cur = set(p["assign"].get(str(day), ""))
    (cur.add if on else cur.discard)(shift)
    if cur:
        p["assign"][str(day)] = "".join(sorted(cur, key="DN".index))
    else:
        p["assign"].pop(str(day), None)


def _pair_ok(members):
    if len(members) != 2:
        return True
    a, b = members
    ad, al, bd, bl = "Kd" in a["role"], "Kr" in a["role"], "Kd" in b["role"], "Kr" in b["role"]
    return (ad and bl) or (bd and al)


def shift_date(month, day):
    y, m = parse_month(month)
    return dt.date(y, m, day)


def label(month, day, shift):
    d = shift_date(month, day)
    return f"{WD[d.weekday()]} {d.strftime('%d.%m')} {shift} ({SHIFT_NAMES[shift]})"


def apply_swap(rep, a_uid, give, b_uid, take=None):
    """Zwraca (nowy_raport, ostrzeżenia). Rzuca SwapError, gdy zamiana łamie twarde warunki."""
    if a_uid == b_uid:
        raise SwapError("Nie można zamieniać się z samym sobą.")
    new = recompute_report(rep)  # kopia
    a, b = person(new, a_uid), person(new, b_uid)
    if not a or not b:
        raise SwapError("Obie osoby muszą występować w tym grafiku.")
    gd, gs = give
    if not holds(a, gd, gs):
        raise SwapError(f"{a['name']} nie ma już zmiany {label(rep['month'], gd, gs)}.")
    if holds(b, gd, gs):
        raise SwapError(f"{b['name']} jest już na zmianie {label(rep['month'], gd, gs)}.")
    affected = {(gd, gs)}
    _toggle(a, gd, gs, False)
    _toggle(b, gd, gs, True)
    if take:
        td, ts = take
        if (td, ts) == (gd, gs):
            raise SwapError("To ta sama zmiana.")
        if not holds(b, td, ts):
            raise SwapError(f"{b['name']} nie ma już zmiany {label(rep['month'], td, ts)}.")
        if holds(a, td, ts):
            raise SwapError(f"{a['name']} jest już na zmianie {label(rep['month'], td, ts)}.")
        affected.add((td, ts))
        _toggle(b, td, ts, False)
        _toggle(a, td, ts, True)

    for d, s in sorted(affected):
        members = [p for p in new["people"] if holds(p, d, s)]
        if len(members) > PER_SHIFT:
            raise SwapError(f"Na zmianie {label(rep['month'], d, s)} byłoby więcej niż {PER_SHIFT} osoby.")
        if not _pair_ok(members):
            raise SwapError(f"Na zmianie {label(rep['month'], d, s)} musi być kierowca i kierownik "
                            f"({' + '.join(m['name'] + ' [' + m['role'] + ']' for m in members)} to niedozwolona para).")
    new = recompute_report(new)
    na, nb = person(new, a_uid), person(new, b_uid)
    for p in (na, nb):
        if p["hours"] > p["max_h"]:
            raise SwapError(f"{p['name']} przekroczyłby maksimum godzin ({p['hours']} h > max {p['max_h']} h).")

    warnings = []
    for before_uid, after in ((a_uid, na), (b_uid, nb)):
        old = person(rep, before_uid)
        if after["b2b"] > old.get("b2b", 0):
            warnings.append(f"{after['name']}: N→D bez przerwy")
        if after["below_min"] and not old.get("below_min", False):
            warnings.append(f"{after['name']}: spadnie poniżej minimum godzin ({after['hours']} h)")
    return new, warnings


def edit_assignment(rep, uid, day, shift, add, extra_person=None):
    """Ręczna edycja administratora: dodaje osobę do zmiany albo zdejmuje ją ze zmiany.

    Twarde (SwapError): osoba/dzień/zmiana poprawne, max 2 osoby na zmianie, a przy 2 osobach para kierowca+kierownik.
    Ostrzeżenia (nie blokują): przekroczone maksimum godzin, N→D bez przerwy, spadek poniżej minimum,
    zmiana z brakami po zdjęciu osoby. Zwraca (nowy_raport, ostrzeżenia).
    """
    new = recompute_report(rep)  # kopia
    if extra_person is not None and person(new, uid) is None:
        new["people"].append(copy.deepcopy(extra_person))  # osoba spoza grafiku (np. bez dyspozycji)
    p = person(new, uid)
    if p is None:
        raise SwapError("Tej osoby nie ma w grafiku.")
    if shift not in ("D", "N") or not (1 <= day <= new["ndays"]):
        raise SwapError("Niepoprawny dzień lub zmiana.")
    where = label(rep["month"], day, shift)
    if add:
        if holds(p, day, shift):
            raise SwapError(f"{p['name']} jest już na zmianie {where}.")
        _toggle(p, day, shift, True)
        members = [x for x in new["people"] if holds(x, day, shift)]
        if len(members) > PER_SHIFT:
            raise SwapError(f"Na zmianie {where} są już {PER_SHIFT} osoby. Najpierw zdejmij jedną z nich.")
        if not _pair_ok(members):
            raise SwapError(f"Na zmianie {where} musi być kierowca i kierownik "
                            f"({' + '.join(m['name'] + ' [' + m['role'] + ']' for m in members)} to niedozwolona para).")
    else:
        if not holds(p, day, shift):
            raise SwapError(f"{p['name']} nie jest na zmianie {where}.")
        _toggle(p, day, shift, False)
    new = recompute_report(new)

    warnings = []
    np_, old = person(new, uid), person(rep, uid)
    if np_["above_max"] and (old is None or not old.get("above_max", False)):
        warnings.append(f"{np_['name']}: przekroczone maksimum godzin ({np_['hours']} h > max {np_['max_h']} h)")
    if np_["b2b"] > (old.get("b2b", 0) if old else 0):
        warnings.append(f"{np_['name']}: N→D bez przerwy")
    if np_["below_min"] and not (old and old.get("below_min", False)):
        warnings.append(f"{np_['name']}: poniżej minimum godzin ({np_['hours']} h)")
    problems = new["slots"][day - 1][shift]["problems"]
    if problems:
        warnings.append(f"zmiana {where}: BRAK ({', '.join(problems)})")
    return new, warnings
