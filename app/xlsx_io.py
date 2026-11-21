"""Formularz Excel (wejście od osoby) i eksport grafiku do Excela."""
import datetime as dt
import zipfile
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from . import law, roles
from .solver import DAY_NAMES, calendar_info, parse_month

F_SHEET = "Dyspozycja"
F_FIRST_DAY_ROW = 8
F_AVAIL_COL = 5

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


class FormError(Exception):
    pass


MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # formularz ma kilkanaście KB; większe pliki odrzucamy
MAX_UNZIPPED_BYTES = 30 * 1024 * 1024  # ochrona przed "bombą" zip (mały plik rozpakowujący się do gigabajtów)


def make_form(month, first="", last="", min_h=None, max_h=None, avail=None, other_hours=None) -> bytes:
    """Formularz dyspozycji jednej osoby (rola i domyślne godziny są w bazie)."""
    year, mon = parse_month(month)
    ndays, off, hol = calendar_info(year, mon)
    avail = avail or {}
    wb = Workbook()
    ws = wb.active
    ws.title = F_SHEET

    ws["A1"], ws["B1"] = "Miesiąc", month
    ws["B1"].number_format = "@"
    ws["A2"], ws["B2"] = "Imię", first
    ws["A3"], ws["B3"] = "Nazwisko", last
    ws["A4"], ws["B4"] = "Min godzin (opcjonalnie)", min_h
    ws["A5"], ws["B5"] = "Max godzin (opcjonalnie)", max_h
    ws["A6"], ws["B6"] = ("Godziny w innych miejscach" if law.law_active(month) else "Godziny u innego pracodawcy (opcjonalnie)"), other_hours
    for r in range(1, 7):
        ws.cell(row=r, column=1).font = BOLD
    for r in (2, 3, 4, 5, 6):
        ws.cell(row=r, column=2).fill = FILL["input"]
    # instrukcja: jeden scalony, zawijany blok (zamiast długich zdań uciętych w wąskiej kolumnie)
    steps = [
        "JAK WYPEŁNIĆ",
        "1.  Wpisz imię i nazwisko (żółte pola po lewej), tak jak w systemie.",
        "2.  Min/max godzin: zostaw puste, to wezmą się wartości domyślne.",
        "3.  Przy każdym dniu wybierz z listy (kolumna „Dostępność”):",
        "      D = dzień 7-19      N = noc 19-7      DN = doba 7-7 (lub samo D / samo N)",
        "      puste = nie mogę tego dnia",
    ]
    if law.law_active(month):
        steps.append("4.  Pracujesz też u innego pracodawcy? Wpisz godziny w tym miesiącu (0 = wcale).")
    ws.merge_cells("D1:H6")
    ws["D1"] = "\n".join(steps)
    ws["D1"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["D1"].fill = FILL["head"]
    ws["D1"].font = Font(size=11)
    for r in range(1, 7):
        ws.row_dimensions[r].height = 26

    for c, title in enumerate(["Dzień", "Data", "Dzień tyg.", "Święto", "Dostępność"], start=1):
        cell = ws.cell(row=F_FIRST_DAY_ROW - 1, column=c, value=title)
        cell.font, cell.fill = BOLD, FILL["head"]
    for d in range(1, ndays + 1):
        r = F_FIRST_DAY_ROW + d - 1
        date = dt.date(year, mon, d)
        ws.cell(row=r, column=1, value=d)
        ws.cell(row=r, column=2, value=date.strftime("%Y-%m-%d"))
        ws.cell(row=r, column=3, value=DAY_NAMES[date.weekday()])
        ws.cell(row=r, column=4, value=hol.get(d, ""))
        a = ws.cell(row=r, column=F_AVAIL_COL, value=avail.get(d))
        a.alignment = Alignment(horizontal="center")
        a.fill = FILL["input"]
        if d in off:
            for c in range(1, 5):
                ws.cell(row=r, column=c).fill = FILL["off"]

    last_row = F_FIRST_DAY_ROW + ndays - 1
    dv = DataValidation(type="list", formula1='"D,N,DN"', allow_blank=True)
    dv.error, dv.errorTitle = "Dozwolone: D, N, DN albo puste.", "Zła wartość"
    ws.add_data_validation(dv)
    dv.add(f"E{F_FIRST_DAY_ROW}:E{last_row}")
    dvn = DataValidation(type="whole", operator="between", formula1="0", formula2="744", allow_blank=True)
    ws.add_data_validation(dvn)
    dvn.add("B4:B6")

    for col, w in zip("ABCDEFGH", (38, 22, 12, 30, 16, 12, 12, 12)):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_form(data: bytes) -> dict:
    """Czyta formularz. Zwraca {month, first, last, min_h, max_h, avail{int: 'D'|'N'|'DN'}}."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise FormError(f"plik jest za duży (limit {MAX_UPLOAD_BYTES // 1024 // 1024} MB); wgraj wypełniony formularz, a nie inny plik")
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > 200 or sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
                raise FormError("plik wygląda na uszkodzony lub nie jest formularzem")
        wb = load_workbook(BytesIO(data), data_only=True)
    except FormError:
        raise
    except Exception:
        raise FormError("nie da się otworzyć pliku (to nie jest poprawny .xlsx)")
    if F_SHEET not in wb.sheetnames:
        raise FormError(f"to nie jest formularz (brak arkusza „{F_SHEET}”)")
    ws = wb[F_SHEET]
    errors = []

    v = ws["B1"].value
    month = f"{v.year}-{v.month:02d}" if isinstance(v, (dt.date, dt.datetime)) else str(v or "").strip()
    try:
        year, mon = parse_month(month)
    except ValueError as e:
        raise FormError(str(e))
    month = f"{year}-{mon:02d}"  # kanoniczna postać (np. "2027-1" → "2027-01"), taka jak w bazie
    ndays, _, _ = calendar_info(year, mon)

    # układ: w kolumnie A numery dni 1..n we właściwych wierszach (wykrywa wstawione/usunięte wiersze)
    for d in range(1, ndays + 1):
        cell = ws.cell(row=F_FIRST_DAY_ROW + d - 1, column=1).value
        if cell != d and str(cell).strip() != str(d):
            raise FormError("układ formularza został zmieniony (nie wstawiaj ani nie usuwaj wierszy i kolumn); "
                            "pobierz formularz ponownie i wpisz dane w żółte pola")

    first = str(ws["B2"].value or "").strip()
    last = str(ws["B3"].value or "").strip()
    if not first or not last:
        errors.append("brak imienia lub nazwiska (B2, B3)")

    limits = []
    for cell, label in (("B4", "min"), ("B5", "max"), ("B6", "godziny w innych miejscach")):
        raw = ws[cell].value
        if raw in (None, ""):
            limits.append(None)
            continue
        try:
            n = int(raw)
            assert n >= 0
            limits.append(n)
        except (TypeError, ValueError, AssertionError):
            limits.append(None)
            errors.append(f"{label} ({cell}) musi być liczbą całkowitą ≥ 0")

    avail = {}
    for d in range(1, ndays + 1):
        val = ws.cell(row=F_FIRST_DAY_ROW + d - 1, column=F_AVAIL_COL).value
        val = "" if val is None else str(val).strip().upper().replace(" ", "")
        if val in ("", "-"):
            continue
        if val == "ND":
            val = "DN"
        if val not in ("D", "N", "DN"):
            errors.append(f"dzień {d}: niepoprawna wartość {val!r} (D / N / DN)")
            continue
        avail[d] = val
    if errors:
        raise FormError("; ".join(errors))
    return {"month": month, "first": first, "last": last, "min_h": limits[0], "max_h": limits[1],
            "other_hours": limits[2], "avail": avail}


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
