"""Solver grafiku karetki: 1 karetka, zmiany D (7-19) i N (19-7), 2 osoby na zmianie.

Reguły na zmianie: 2 osoby, w tym >= 1 z prawem prowadzenia i >= 1 kierownik
(osoba z obiema rolami może pełnić obie). Dla 2 osób te dwa warunki wystarczą:
odpadają dokładnie pary kierowca+kierowca i kierownik+kierownik.
Logika układania: patrz solve() (etapy: minimum → braki → najmniej godzin → uciążliwość → losowanie).
"""
import calendar
import datetime as dt
import math
import os
import random
from dataclasses import dataclass
from functools import lru_cache

import holidays
from ortools.sat.python import cp_model

HOURS = 12  # długość jednej zmiany (D lub N); doba = 2 zmiany
PER_SHIFT = 2  # osób na zmianę
DAY_NAMES = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]

# Wagi etapu 4 (uciążliwość i przerwa po nocy); etapy 1-3 i 5 nie mają wag, bo są leksykograficzne.
W_B2B = 1_500  # N (lub doba) dnia d i D dnia d+1: zero przerwy
W_BURDEN = 8  # za 1/100 punktu odchylenia od oczekiwanych uciążliwych zmian
SALDO_ALPHA = 0.5  # jak mocno saldo z poprzednich miesięcy koryguje oczekiwania


@dataclass
class Person:
    uid: int
    name: str
    can_drive: bool
    can_lead: bool
    min_h: int
    max_h: int
    saldo: float = 0.0
    law_note: str = ""  # niepuste, gdy limit ustawowy obniżył max h

    @property
    def role_code(self):
        return "Kd/Kr" if self.can_drive and self.can_lead else ("Kd" if self.can_drive else "Kr")


# --------------------------------------------------------------------------
# Kalendarz
# --------------------------------------------------------------------------
def parse_month(s):
    try:
        y, m = str(s).strip().split("-")
        y, m = int(y), int(m)
        assert 1 <= m <= 12 and 2000 <= y <= 2100
        return y, m
    except Exception:
        raise ValueError(f"Zły format miesiąca: {s!r} (oczekiwane RRRR-MM, np. 2027-01)")


@lru_cache(maxsize=64)
def calendar_info(year, month):
    """Zwraca (ndays, off: set dni wolnych/świąt, hol: dict dzień->nazwa)."""
    ndays = calendar.monthrange(year, month)[1]
    hol = holidays.country_holidays("PL", years=year)
    off, names = set(), {}
    for d in range(1, ndays + 1):
        date = dt.date(year, month, d)
        if date.weekday() >= 5:
            off.add(d)
        if date in hol:
            off.add(d)
            names[d] = hol.get(date)
    return ndays, frozenset(off), names


# --------------------------------------------------------------------------
# Diagnostyka wstępna (przed liczeniem)
# --------------------------------------------------------------------------
def precheck(persons, avail, ndays):
    lines, problems = [], 0
    demand_h = ndays * 2 * PER_SHIFT * HOURS
    smin = sum(p.min_h for p in persons)
    smax = sum(p.max_h for p in persons)
    lines.append(f"Osób z dyspozycją: {len(persons)} "
                 f"({sum(p.can_drive and not p.can_lead for p in persons)} tylko kierowców, "
                 f"{sum(p.can_lead and not p.can_drive for p in persons)} tylko kierowników, "
                 f"{sum(p.can_drive and p.can_lead for p in persons)} kierowca/kierownik)")
    lines.append(f"Zapotrzebowanie: {demand_h} h ({ndays} dni x 2 zmiany x {PER_SHIFT} osoby x {HOURS} h)")
    lines.append(f"Suma min h: {smin}, suma max h: {smax}")
    if smin > demand_h:
        lines.append("UWAGA: suma minimów > zapotrzebowanie: nie wszyscy dostaną swoje minimum.")
    if smax < demand_h:
        lines.append("UWAGA: suma maksimów < zapotrzebowanie: grafik nie może być w pełni obsadzony.")
    for per in persons:
        if per.law_note:
            lines.append(f"USTAWA: {per.name}: {per.law_note}")
    for p, per in enumerate(persons):
        cap_h = sum(2 * HOURS if v == "DN" else HOURS for v in avail[p].values())
        if cap_h < per.min_h:
            lines.append(f"UWAGA: {per.name} zadeklarował dostępność na {cap_h} h, a minimum to {per.min_h} h.")
    for d in range(1, ndays + 1):
        for s in "DN":
            can = [i for i in range(len(persons)) if s in avail[i].get(d, "")]
            issues = []
            if len(can) < PER_SHIFT:
                issues.append(f"dostępnych tylko {len(can)} os.")
            if not any(persons[i].can_drive for i in can):
                issues.append("brak dostępnego kierowcy")
            if not any(persons[i].can_lead for i in can):
                issues.append("brak dostępnego kierownika")
            if issues:
                problems += 1
                lines.append(f"dzień {d} {s}: " + ", ".join(issues))
    if problems == 0:
        lines.append("Każda zmiana ma dość dostępnych osób, kierowcę i kierownika (to jeszcze nie gwarancja obsady).")
    return lines


# --------------------------------------------------------------------------
# Model CP-SAT
# --------------------------------------------------------------------------
def solve(persons, avail, ndays, off, time_limit, log=False, seed=None):
    """Układa grafik etapami (kolejność ważności, każdy etap blokuje wynik poprzedniego):

    1. każdy dobija do swojego minimum godzin (min. sumaryczny niedobór),
    2. dopiero potem uzupełniane są braki w obsadzie (osoba / kierowca / kierownik),
    3. nadwyżki godzin trafiają do osób, które mają ich najmniej (minimalizacja sumy kwadratów godzin),
    4. równa uciążliwość (noce, weekendy, święta, saldo) i unikanie N→D bez przerwy,
    5. remisy rozstrzyga losowanie (seed).

    Twarde: dostępność, max h, max 2 osoby na zmianie, brak pary dwóch osób bez prawa
    prowadzenia lub dwóch kierowców bez uprawnień kierownika (kierowca+kierowca, kierownik+kierownik).
    """
    seed = seed if seed is not None else random.randrange(1, 10**6)
    rng = random.Random(seed)
    P = range(len(persons))
    days = range(1, ndays + 1)
    m = cp_model.CpModel()
    BIG = 10**9

    x = {}
    for p in P:
        for d in days:
            a = avail[p].get(d, "")
            for s in "DN":
                if s in a:
                    x[p, d, s] = m.NewBoolVar(f"x_{p}_{d}_{s}")

    def total(terms, name):
        t = m.NewIntVar(0, BIG, name)
        m.Add(t == (sum(terms) if terms else 0))
        return t

    # Obsada: <= 2 osoby; w każdej zmianie max 1 osoba tylko-kierowca i max 1 tylko-kierownik (twarde)
    drive_only = {p for p in P if persons[p].can_drive and not persons[p].can_lead}
    lead_only = {p for p in P if persons[p].can_lead and not persons[p].can_drive}
    gap_terms = []
    for d in days:
        for s in "DN":
            ppl = [p for p in P if (p, d, s) in x]
            g = m.NewIntVar(0, PER_SHIFT, f"gap_{d}_{s}")
            m.Add(sum(x[p, d, s] for p in ppl) + g == PER_SHIFT)
            m.Add(sum(x[p, d, s] for p in ppl if p in drive_only) <= 1)
            m.Add(sum(x[p, d, s] for p in ppl if p in lead_only) <= 1)
            gd = m.NewBoolVar(f"gapdrv_{d}_{s}")
            m.Add(sum(x[p, d, s] for p in ppl if persons[p].can_drive) + gd >= 1)
            gl = m.NewBoolVar(f"gaplead_{d}_{s}")
            m.Add(sum(x[p, d, s] for p in ppl if persons[p].can_lead) + gl >= 1)
            gap_terms += [g, gd, gl]

    # Godziny osób (w zmianach po 12 h)
    ns, cap, mins, maxs, shorts, sqs = {}, {}, {}, {}, [], []
    for p in P:
        terms = [x[p, d, s] for d in days for s in "DN" if (p, d, s) in x]
        cap[p] = len(terms)
        ns[p] = m.NewIntVar(0, cap[p], f"ns_{p}")
        m.Add(ns[p] == (sum(terms) if terms else 0))
        mx = persons[p].max_h // HOURS
        mn = min(math.ceil(persons[p].min_h / HOURS), mx)
        mins[p], maxs[p] = mn, mx
        m.Add(ns[p] <= mx)  # max twardy
        short = m.NewIntVar(0, mn, f"short_{p}")
        m.Add(ns[p] + short >= mn)  # niedobór poniżej minimum
        shorts.append(short)
        sq = m.NewIntVar(0, cap[p] * cap[p], f"sq_{p}")
        m.AddMultiplicationEquality(sq, [ns[p], ns[p]])
        sqs.append(sq)

    # Oczekiwana uciążliwość (referencja do wyrównania noc/weekend/święto, etap 4)
    demand_s = ndays * 2 * PER_SHIFT
    smin, smax = sum(mins.values()), sum(maxs.values())
    t = 0.0 if smax == smin else min(1.0, max(0.0, (demand_s - smin) / (smax - smin)))
    fair = {p: min(mins[p] + t * (maxs[p] - mins[p]), cap[p]) for p in P}

    def burden(d, s):
        return (1 if s == "N" else 0) + (1 if d in off else 0)

    total_b = sum(PER_SHIFT * burden(d, s) for d in days for s in "DN")
    sf = sum(fair.values()) or 1.0
    mean_saldo = sum(p.saldo for p in persons) / len(persons)
    expected = {p: total_b * fair[p] / sf for p in P}
    soft_terms = []
    for p in P:
        terms = [burden(d, s) * x[p, d, s] for d in days for s in "DN" if (p, d, s) in x]
        bp = m.NewIntVar(0, 2 * ndays, f"b_{p}")
        m.Add(bp == (sum(terms) if terms else 0))
        target = expected[p] - SALDO_ALPHA * (persons[p].saldo - mean_saldo)
        t100 = round(100 * max(0.0, target))
        dev = m.NewIntVar(0, 10_000_000, f"devb_{p}")
        m.Add(dev >= 100 * bp - t100)
        m.Add(dev >= t100 - 100 * bp)
        soft_terms.append(W_BURDEN * dev)
    for p in P:
        for d in range(1, ndays):
            if (p, d, "N") in x and (p, d + 1, "D") in x:
                z = m.NewBoolVar(f"b2b_{p}_{d}")
                m.Add(z >= x[p, d, "N"] + x[p, d + 1, "D"] - 1)
                soft_terms.append(W_B2B * z)
    rand_terms = [rng.randint(0, 1000) * v for v in x.values()]

    # Doby mają pierwszeństwo: kto zadeklarował DN w danym dniu, ma dostać całą dobę (D+N), a nie
    # pojedynczą zmianę. Kara = liczba "połówek" przydzielonych osobom z DN (D lub N bez drugiej zmiany).
    split_terms = []
    for p in P:
        for d in days:
            if (p, d, "D") in x and (p, d, "N") in x:  # tylko dni zadeklarowane jako DN
                y = m.NewBoolVar(f"doba_{p}_{d}")
                m.Add(y <= x[p, d, "D"])
                m.Add(y <= x[p, d, "N"])
                m.Add(y >= x[p, d, "D"] + x[p, d, "N"] - 1)
                split_terms.append(x[p, d, "D"] + x[p, d, "N"] - 2 * y)

    stages = [
        ("minimum godzin (niedobór, w zmianach)", shorts, 0.10),
        ("braki w obsadzie", gap_terms, 0.15),
        ("doby: zmiany połówkowe osób z DN", split_terms, 0.15),
        ("wyrównanie godzin (suma kwadratów)", sqs, 0.25),
        ("uciążliwość i przerwa po nocy", soft_terms, 0.15),
        ("losowanie remisów", rand_terms, 0.20),
    ]
    results, solver = [], None
    for i, (name, terms, frac) in enumerate(stages):
        expr = total(terms, f"stage{i}")
        m.Minimize(expr)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(2.0, time_limit * frac)
        solver.parameters.num_workers = os.cpu_count() or 4
        solver.parameters.random_seed = seed % 1000
        solver.parameters.log_search_progress = log
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"Solver nie znalazł rozwiązania (etap „{name}”): {solver.StatusName(status)}")
        val = round(solver.ObjectiveValue())
        results.append({"name": name, "value": val, "status": solver.StatusName(status)})
        m.Add(expr <= val)  # kolejne etapy nie mogą pogorszyć tego
        m.ClearHints()
        for v in x.values():
            m.AddHint(v, solver.Value(v))

    assign = {}  # (p, d) -> "D" | "N" | "DN"
    for (p, d, s), var in x.items():
        if solver.Value(var):
            assign[p, d] = "".join(sorted(assign.get((p, d), "") + s, key="DN".index))
    meta = {
        "status": "OPTIMAL" if all(r["status"] == "OPTIMAL" for r in results) else "FEASIBLE",
        "stages": results,
        "seed": seed,
        "expected_b": {p: expected[p] for p in P},
    }
    return assign, meta


# --------------------------------------------------------------------------
# Raport (słownik JSON-owalny: do HTML, bazy i Excela)
# --------------------------------------------------------------------------
def build_report(month, persons, avail, assign, meta, pre_lines, missing):
    year, mon = parse_month(month)
    ndays, off, hol = calendar_info(year, mon)
    days = [{"d": d, "wd": DAY_NAMES[dt.date(year, mon, d).weekday()], "hol": hol.get(d, ""), "off": d in off}
            for d in range(1, ndays + 1)]

    slots, gaps = [], 0
    for d in range(1, ndays + 1):
        row = {"d": d}
        for s in "DN":
            idx = [p for p in range(len(persons)) if s in assign.get((p, d), "")]
            probs = []
            if len(idx) < PER_SHIFT:
                probs.append(f"brak {PER_SHIFT - len(idx)} os.")
            if not any(persons[p].can_drive for p in idx):
                probs.append("brak kierowcy")
            if not any(persons[p].can_lead for p in idx):
                probs.append("brak kierownika")
            gaps += bool(probs)
            row[s] = {"people": [f"{persons[p].name} [{persons[p].role_code}]" for p in idx], "problems": probs}
        slots.append(row)

    people = []
    for p, per in enumerate(persons):
        sh = [(d, s) for d in range(1, ndays + 1) for s in assign.get((p, d), "")]
        b = sum((1 if s == "N" else 0) + (1 if d in off else 0) for d, s in sh)
        b2b = sum(1 for d in range(1, ndays) if "N" in assign.get((p, d), "") and "D" in assign.get((p, d + 1), ""))
        hours = len(sh) * HOURS
        exp = meta["expected_b"][p]
        notes = []
        if per.law_note:
            notes.append(per.law_note)
        # minimum liczone w pełnych zmianach (jak w modelu), ale nie więcej niż mieści się w max h
        min_eff = min(math.ceil(per.min_h / HOURS), per.max_h // HOURS) * HOURS
        below_min = hours < min_eff
        if below_min:
            cap_h = sum(2 * HOURS if v == "DN" else HOURS for v in avail[p].values())
            notes.append("poniżej minimum" + (" (za mało zadeklarowanej dostępności)" if cap_h < per.min_h else ""))
        if b2b:
            notes.append("N→D bez przerwy")
        people.append({
            "uid": per.uid, "name": per.name, "role": per.role_code,
            "min_h": per.min_h, "max_h": per.max_h, "hours": hours, "n": len(sh),
            "doby": sum(1 for d in range(1, ndays + 1) if assign.get((p, d)) == "DN"),
            "nights": sum(1 for _, s in sh if s == "N"),
            "offs": sum(1 for d, _ in sh if d in off),
            "b": b, "expected": round(exp, 1), "b2b": b2b,
            "saldo_old": per.saldo, "saldo_new": round(per.saldo + b - exp, 1),
            "notes": notes, "law_limited": bool(per.law_note), "law_note": per.law_note, "below_min": below_min,
            "assign": {str(d): assign[p, d] for d in range(1, ndays + 1) if (p, d) in assign},
        })

    return {
        "month": month, "ndays": ndays, "days": days, "people": people, "slots": slots, "gaps": gaps,
        "status": meta["status"], "stages": meta["stages"], "seed": meta["seed"],
        "pre": pre_lines, "missing": missing,
    }


def recompute_report(rep):
    """Przelicza pola pochodne raportu (obsada, godziny, uciążliwość, braki) po ręcznej zmianie `assign`.

    Używane przy zamianach: raport przechowuje wszystko, czego trzeba (role, limity, saldo).
    Zwraca nowy raport (kopię).
    """
    import copy

    rep = copy.deepcopy(rep)
    ndays = rep["ndays"]
    off = {x["d"] for x in rep["days"] if x["off"]}
    people = rep["people"]
    drive = [("Kd" in p["role"]) for p in people]
    lead = [("Kr" in p["role"]) for p in people]

    gaps = 0
    for row in rep["slots"]:
        d = row["d"]
        for s in "DN":
            idx = [i for i, p in enumerate(people) if s in p["assign"].get(str(d), "")]
            probs = []
            if len(idx) < PER_SHIFT:
                probs.append(f"brak {PER_SHIFT - len(idx)} os.")
            if not any(drive[i] for i in idx):
                probs.append("brak kierowcy")
            if not any(lead[i] for i in idx):
                probs.append("brak kierownika")
            gaps += bool(probs)
            row[s] = {"people": [f"{people[i]['name']} [{people[i]['role']}]" for i in idx], "problems": probs}
    rep["gaps"] = gaps

    for p in people:
        a = p["assign"]
        sh = [(int(d), s) for d, v in a.items() for s in v]
        hours = len(sh) * HOURS
        b = sum((1 if s == "N" else 0) + (1 if d in off else 0) for d, s in sh)
        b2b = sum(1 for d in range(1, ndays) if "N" in a.get(str(d), "") and "D" in a.get(str(d + 1), ""))
        cap_flag = any("za mało zadeklarowanej" in n for n in p.get("notes", []))
        min_eff = min(math.ceil(p["min_h"] / HOURS), p["max_h"] // HOURS) * HOURS
        below_min = hours < min_eff
        notes = []
        if p.get("law_note"):
            notes.append(p["law_note"])
        if below_min:
            notes.append("poniżej minimum" + (" (za mało zadeklarowanej dostępności)" if cap_flag else ""))
        above_max = hours > p["max_h"]
        if above_max:
            notes.append(f"powyżej maksimum godzin ({hours} h > max {p['max_h']} h)")
        if b2b:
            notes.append("N→D bez przerwy")
        p.update({
            "hours": hours, "n": len(sh),
            "doby": sum(1 for v in a.values() if v == "DN"),
            "nights": sum(1 for _, s in sh if s == "N"),
            "offs": sum(1 for d, _ in sh if d in off),
            "b": b, "b2b": b2b, "saldo_new": round(p["saldo_old"] + b - p["expected"], 1),
            "notes": notes, "below_min": below_min, "above_max": above_max,
        })
    return rep
