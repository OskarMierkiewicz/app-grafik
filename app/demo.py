"""Dane demo: losowi użytkownicy i ich dyspozycje na miesiąc.

  python -m app.demo --month 2027-01 --users 12
  python -m app.demo --month 2027-01 --users 12 --export przyklad   # dodatkowo zapisuje pliki i gotowy grafik
  python -m app.demo --month 2026-12 --users 12 --trim               # zostaw tylko 12 osób demo (usuń nadmiarowe)
"""
import argparse
import csv
import os
import random

from sqlalchemy import select

from .auth import default_login, hash_password
from . import law, solver
from .db import SessionLocal, init_db
from .models import Schedule, ScheduleEdit, Submission, Swap, User, UserAccount
from .solver import calendar_info, parse_month
from .xlsx_io import make_form, write_schedule

FIRST = ["Jan", "Anna", "Piotr", "Maria", "Tomasz", "Katarzyna", "Michał", "Agnieszka", "Paweł", "Ewa",
         "Marcin", "Joanna", "Łukasz", "Magdalena", "Krzysztof", "Monika", "Adam", "Natalia", "Rafał", "Zofia"]
LAST = ["Kowalski", "Nowak", "Wiśniewski", "Wójcik", "Kamiński", "Lewandowski", "Zieliński", "Szymański", "Woźniak",
        "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski", "Krawczyk", "Piotrowski", "Grabowski", "Pawłowski",
        "Michalski", "Król"]


DEMO_PASSWORD = "demo12345"  # hasło wszystkich użytkowników demo (login: imię.nazwisko, np. jan.kowalski)
NON_DRIVERS = {3, 8}  # indeksy osób demo, które nie są kierowcami (reszta jest)


def demo_name(i):
    """Imię i nazwisko osoby demo o indeksie i (to samo, co przy tworzeniu)."""
    return FIRST[i % len(FIRST)], LAST[(i * 7 + i // len(FIRST)) % len(LAST)]


def trim_demo_users(db, keep):
    """Usuwa osoby demo o indeksach >= keep (z kontami, dyspozycjami, zamianami i wpisami dziennika).

    Rozpoznaje je po imieniu i nazwisku generowanym przez demo, więc prawdziwa osoba o takim samym imieniu
    i nazwisku też zostałaby usunięta. Wygenerowane wcześniej grafiki zostają (usuń je w panelu admina).
    """
    removed = []
    for i in range(keep, 200):
        first, last = demo_name(i)
        u = db.scalar(select(User).where(User.first_name == first, User.last_name == last))
        if u is None:
            continue
        db.query(Submission).filter(Submission.user_id == u.id).delete()
        db.query(Swap).filter((Swap.requester_id == u.id) | (Swap.partner_id == u.id)).delete()
        db.query(ScheduleEdit).filter(ScheduleEdit.user_id == u.id).delete()
        db.delete(u)  # konto usuwa się kaskadowo
        removed.append(u.full_name)
    db.flush()
    return removed


def export_example(db, month, users, out):
    """Zapisuje przykład do folderu: pliki dyspozycji (dla użytkowników i dla admina), grafik i opis osób."""
    year, mon = parse_month(month)
    ndays, off, _ = calendar_info(year, mon)
    per_user = os.path.join(out, "dyspozycje_uzytkownikow")  # <login>/RRRR-MM.xlsx: tak wgrywa użytkownik
    flat = os.path.join(out, "dyspozycje_dla_admina")  # <login>.xlsx: do hurtowego wgrania w panelu admina
    os.makedirs(flat, exist_ok=True)
    persons, avail, rows = [], [], []
    for u in users:
        sub = db.scalar(select(Submission).where(Submission.user_id == u.id, Submission.month == month))
        av = {int(d): v for d, v in sub.avail.items()}
        login = u.account.login
        data = make_form(month, u.first_name, u.last_name, sub.min_h, sub.max_h, av, sub.other_hours)
        os.makedirs(os.path.join(per_user, login), exist_ok=True)
        for path in (os.path.join(per_user, login, f"{month}.xlsx"), os.path.join(flat, f"{login}.xlsx")):
            with open(path, "wb") as fh:
                fh.write(data)
        mn = sub.min_h if sub.min_h is not None else u.min_h
        mx = sub.max_h if sub.max_h is not None else u.max_h
        mn, mx, note = law.apply_limit(month, u.only_job, sub.other_hours, mx, mn)
        persons.append(solver.Person(u.id, u.full_name, u.can_drive, u.can_lead, mn, mx, u.saldo, note))
        avail.append(av)
        rows.append([login, u.full_name, "kierowca + kierownik" if u.can_drive else "tylko kierownik",
                     f"{mn}-{mx}", "własne (z pliku)" if sub.min_h is not None else "domyślne z bazy",
                     "tak" if u.only_job else f"nie ({sub.other_hours} h gdzie indziej)"])
    pre = solver.precheck(persons, avail, ndays)
    assign, meta = solver.solve(persons, avail, ndays, off, 30)
    rep = solver.build_report(month, persons, avail, assign, meta, pre, [])
    with open(os.path.join(out, f"grafik_{month}_admin.xlsx"), "wb") as fh:
        fh.write(write_schedule(rep))
    with open(os.path.join(out, f"grafik_{month}_dla_uzytkownikow.xlsx"), "wb") as fh:
        fh.write(write_schedule(rep, public=True))
    with open(os.path.join(out, "osoby.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["login", "osoba", "rola", "godziny min-max", "źródło limitów", "jedyne miejsce pracy"])
        w.writerows(rows)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--users", type=int, default=12)
    ap.add_argument("--export", metavar="FOLDER", help="zapisz pliki dyspozycji i gotowy grafik do folderu")
    ap.add_argument("--trim", action="store_true",
                    help="usuń osoby demo spoza pierwszych --users (np. po wcześniejszym uruchomieniu z 20 osobami)")
    a = ap.parse_args()
    year, mon = parse_month(a.month)
    ndays, _, _ = calendar_info(year, mon)
    rng = random.Random(7)
    init_db()
    with SessionLocal() as db:
        removed = trim_demo_users(db, a.users) if a.trim else []
        created = []
        for i in range(a.users):
            first, last = demo_name(i)
            u = db.scalar(select(User).where(User.first_name == first, User.last_name == last))
            if u is None:
                u = User(first_name=first, last_name=last, can_lead=True, only_job=(i % 3 != 0),
                         min_h=rng.choice([72, 84, 96, 108]), max_h=rng.choice([144, 168, 192]))
                db.add(u)
            # kierownikiem jest każdy (domyślnie); kierowcami wszyscy poza dwiema osobami (NON_DRIVERS)
            u.can_drive = i not in NON_DRIVERS
            u.can_lead = True
            if u.account is None:
                u.account = UserAccount(login=default_login(first, last), email=f"{default_login(first, last)}@example.com",
                                        password_hash=hash_password(DEMO_PASSWORD))
            db.flush()
            created.append(u)
            avail = {str(d): rng.choice(["D", "N", "DN", "DN", "DN"]) for d in range(1, ndays + 1) if rng.random() >= 0.45}
            sub = db.scalar(select(Submission).where(Submission.user_id == u.id, Submission.month == a.month))
            if sub is None:
                sub = Submission(user_id=u.id, month=a.month)
                db.add(sub)
            sub.avail, sub.source = avail, "demo"
            # kto nie ma only_job, podaje godziny w innych miejscach (część dużo, więc limit ustawowy zadziała)
            sub.other_hours = None if u.only_job else rng.choice([0, 60, 120, 200, 260])
            # co 4. osoba podaje własne limity, reszta bierze domyślne z bazy
            sub.min_h, sub.max_h = (u.min_h, u.max_h) if i % 4 == 0 else (None, None)
        db.commit()
        if a.export:
            rep = export_example(db, a.month, created, a.export)
            print(f"Przykład zapisany w: {os.path.abspath(a.export)} (braki w obsadzie: {rep['gaps']}, "
                  f"poniżej minimum: {sum(p['below_min'] for p in rep['people'])} os., status solvera: {rep['status']})")
    if a.trim:
        print(f"Usunięto nadmiarowe osoby demo ({len(removed)}): {', '.join(removed) if removed else 'brak'}")
    print(f"Dodano/zaktualizowano {a.users} użytkowników z dyspozycjami na {a.month}")
    print(f"Logowanie użytkowników demo: login imię.nazwisko (np. jan.kowalski), hasło: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
