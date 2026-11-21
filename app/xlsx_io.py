"""Formularz Excel (wejście od osoby) i eksport grafiku do Excela."""
import datetime as dt
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import law, roles
from .solver import DAY_NAMES, calendar_info, parse_month

FILL = {
    "D": PatternFill("solid", fgColor="FFE699"),
    "N": PatternFill("solid", fgColor="9DC3E6"),
    "DN": PatternFill("solid", fgColor="C9A0DC"),
    "off": PatternFill("solid", fgColor="F4B183"),
    "bad": PatternFill("solid", fgColor="FF7C80"),
    "warn": PatternFill("solid", fgColor="FFC7CE"),
    "head": PatternFill("solid", fgColor="D9D9D9"),
    "input": PatternFill("solid", fgColor="FFF2CC"),
}
BOLD = Font(bold=True)


def write_schedule(rep: dict, public: bool = False) -> bytes:
    """Eksport raportu grafiku do Excela (Grafik, Obsada, Podsumowanie, Diagnostyka).

    public=True: wersja dla zwykłych użytkowników, tylko Grafik i Obsada, bez min/max godzin, salda, notatek ani diagnostyki.
    """
    days, ndays = rep["days"], rep["ndays"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Grafik"
    ws.append(["Osoba"] + [x["d"] for x in days] + ["Godz."] + ([] if public else ["Min", "Max"]))
    ws.append([""] + [x["wd"] + ("*" if x["hol"] else "") for x in days])
    for i, x in enumerate(days, start=2):
        for r in (1, 2):
            c = ws.cell(row=r, column=i)
            c.font, c.alignment = BOLD, Alignment(horizontal="center")
            c.fill = FILL["off"] if x["off"] else FILL["head"]
    for p in rep["people"]:
        ws.append([f"{p['name']} {roles.icon(p['role'])}"] + [p["assign"].get(str(x["d"]), "") for x in days]
                  + [p["hours"]] + ([] if public else [p["min_h"], p["max_h"]]))
        r = ws.max_row
        for i, x in enumerate(days, start=2):
            v = p["assign"].get(str(x["d"]), "")
            c = ws.cell(row=r, column=i)
            c.alignment = Alignment(horizontal="center")
            if v:
                c.fill = FILL[v]
            elif x["off"]:
                c.fill = FILL["off"]  # cała kolumna weekendu/święta w kolorze nagłówka
        if p["below_min"] and not public:
            ws.cell(row=r, column=ndays + 2).fill = FILL["warn"]
    for s, label in (("D", "Obsada D"), ("N", "Obsada N")):
        ws.append([label] + ["OK" if not row[s]["problems"] else "BRAK" for row in rep["slots"]])
        r = ws.max_row
        ws.cell(row=r, column=1).font = BOLD
        for i, row in enumerate(rep["slots"], start=2):
            c = ws.cell(row=r, column=i)
            c.alignment = Alignment(horizontal="center")
            if row[s]["problems"]:
                c.fill = FILL["bad"]
            elif days[i - 2]["off"]:
                c.fill = FILL["off"]
    ws.append([])
    ws.append([roles.LEGEND])  # legenda ról pod grafikiem
    ws.column_dimensions["A"].width = 34
    for i in range(2, ndays + 2):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 5
    ws.freeze_panes = "B3"

    wo = wb.create_sheet("Obsada")
    wo.append(["Dzień", "", "Zmiana D (7-19)", "Status D", "Zmiana N (19-7)", "Status N"])
    for c in wo[1]:
        c.font, c.fill = BOLD, FILL["head"]
    for x, row in zip(days, rep["slots"]):
        wo.append([x["d"], x["wd"] + (f" ({x['hol']})" if x["hol"] else ""),
                   roles.tags(", ".join(row["D"]["people"])), "OK" if not row["D"]["problems"] else "BRAK: " + ", ".join(row["D"]["problems"]),
                   roles.tags(", ".join(row["N"]["people"])), "OK" if not row["N"]["problems"] else "BRAK: " + ", ".join(row["N"]["problems"])])
        r = wo.max_row
        for col, s in ((4, "D"), (6, "N")):
            if row[s]["problems"]:
                wo.cell(row=r, column=col).fill = FILL["bad"]
        if x["off"]:
            wo.cell(row=r, column=1).fill = FILL["off"]
            wo.cell(row=r, column=2).fill = FILL["off"]
    for col, w in zip("ABCDEF", (6, 24, 46, 28, 46, 28)):
        wo.column_dimensions[col].width = w
    wo.append([])
    wo.append([roles.LEGEND])

    if public:
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    wp = wb.create_sheet("Podsumowanie")
    wp.append(["Osoba", "Rola", "Min h", "Max h", "Godziny", "Zmian", "Dób (DN)", "Nocy", "Dni wolne/święta",
               "Pkt uciążliwości", "Oczekiwane pkt", "Saldo stare", "Saldo nowe", "Bez przerwy (N→D)", "Uwagi"])
    for c in wp[1]:
        c.font, c.fill = BOLD, FILL["head"]
        c.alignment = Alignment(wrap_text=True)
    for p in rep["people"]:
        wp.append([p["name"], roles.full(p["role"]), p["min_h"], p["max_h"], p["hours"], p["n"], p["doby"], p["nights"],
                   p["offs"], p["b"], p["expected"], p["saldo_old"], p["saldo_new"], p["b2b"], "; ".join(p["notes"])])
        if p["notes"]:
            wp.cell(row=wp.max_row, column=15).fill = FILL["warn"]
    for i, w in enumerate((26, 8, 7, 7, 9, 8, 10, 7, 14, 14, 14, 11, 11, 16, 40), start=1):
        wp.column_dimensions[wp.cell(row=1, column=i).column_letter].width = w
    wp.freeze_panes = "B2"

    wd = wb.create_sheet("Diagnostyka")
    wd.append([f"Miesiąc: {rep['month']}"])
    wd.append([f"Status solvera: {rep['status']}, losowanie remisów: seed {rep['seed']}"])
    for st in rep["stages"]:
        wd.append([f"  etap „{st['name']}”: {st['value']} ({st['status']})"])
    wd.append([f"Zmian z brakami w obsadzie: {rep['gaps']}"])
    if rep["missing"]:
        wd.append([f"Bez dyspozycji (nieuwzględnieni): {', '.join(rep['missing'])}"])
    wd.append([])
    wd.append(["Raport wstępny (przed liczeniem)"])
    wd.cell(row=wd.max_row, column=1).font = BOLD
    for line in rep["pre"]:
        wd.append([line])
    wd.column_dimensions["A"].width = 110

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
