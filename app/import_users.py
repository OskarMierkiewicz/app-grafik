"""Import użytkowników z pliku CSV do bazy (Postgres w Dockerze albo SQLite lokalnie).

  docker compose exec -T web python -m app.import_users - < osoby.csv            # plik z Twojego komputera przez stdin
  docker compose exec -T web python -m app.import_users - --dry-run < osoby.csv  # tylko podgląd, nic nie zapisuje
  python -m app.import_users osoby.csv                                           # lokalnie, bez Dockera
  docker compose exec -T web python -m app.import_users - --sync < osoby.csv     # baza ma zawierać TYLKO osoby z pliku

Kolumny są rozpoznawane po nagłówkach (wielkość liter i kolejność bez znaczenia, separator ; lub ,):
  login                  opcjonalnie (domyślnie imię.nazwisko bez polskich znaków)
  osoba                  "Imię Nazwisko" (albo osobne kolumny "imię" i "nazwisko")
  rola                   "kierownik", "kierowca + kierownik", "tylko kierowca" (puste = kierownik)
  godziny min-max        np. "96-144" (albo osobne kolumny min/max); puste = domyślne z bazy
  jedyne miejsce pracy   "tak" / "nie" (domyślnie tak)
  e-mail                 opcjonalnie
  hasło                  opcjonalnie, min. 8 znaków; bez niego nowe osoby dostają losowe hasło (wypisane na końcu)

Istniejące osoby (to samo imię i nazwisko) są aktualizowane. Bez --sync nic nie jest usuwane. Z --sync osoby, których nie ma
w pliku, są USUWANE razem z kontami, dyspozycjami i zamianami (najpierw użyj --dry-run, żeby zobaczyć listę). Hasło istniejącej osoby zmienia się
tylko wtedy, gdy podasz je w pliku. Dane są najpierw w całości sprawdzane: przy jakimkolwiek błędzie nic się nie zapisuje.
"""
import argparse
import csv
import io
import re
import secrets
import sys
import unicodedata

from sqlalchemy import select

from . import auth
from .db import SessionLocal, init_db
from .models import DEFAULT_MAX_H, DEFAULT_MIN_H, ScheduleEdit, Submission, Swap, User, UserAccount

ALIASES = {
    "login": {"login", "uzytkownik", "user"},
    "osoba": {"osoba", "imie i nazwisko", "nazwisko i imie", "pracownik"},
    "imie": {"imie"},
    "nazwisko": {"nazwisko"},
    "rola": {"rola", "stanowisko"},
    "godziny": {"godziny min-max", "godziny", "min-max", "min max"},
    "min": {"min", "min h", "min godzin", "minimum"},
    "max": {"max", "max h", "max godzin", "maksimum"},
    "only_job": {"jedyne miejsce pracy", "only_job", "jedyna praca"},
    "email": {"e-mail", "email", "mail"},
    "haslo": {"haslo", "password", "has?o"},
}
PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez znaków łatwych do pomylenia (0/O, 1/l/I)


def plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("ł", "l").replace("Ł", "L"))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).casefold().split())


def norm_name(first: str, last: str) -> str:
    return plain(f"{first} {last}")


def parse_role(text: str):
    """→ (can_drive, can_lead, opis) albo None, gdy nie rozumiemy."""
    t = plain(text)
    if t in ("", "kierownik"):
        return False, True, "tylko kierownik"
    drive, lead = "kierowc" in t, "kierowni" in t
    if drive and lead:
        return True, True, "kierowca + kierownik"
    if drive and "tylko" in t:
        return True, False, "tylko kierowca"
    if drive:  # samo "kierowca": kierownikiem jest domyślnie każdy
        return True, True, "kierowca + kierownik"
    return None


def read_rows(text: str):
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        sys.exit("Plik jest pusty.")
    cols = {}
    for i, h in enumerate(rows[0]):
        for key, names in ALIASES.items():
            if plain(h) in names and key not in cols:
                cols[key] = i
    return cols, rows[1:]


def parse(text: str):
    """Zwraca (lista rekordów, lista błędów). Numery wierszy liczone jak w edytorze (nagłówek = 1)."""
    cols, rows = read_rows(text)
    errors = []
    if "osoba" not in cols and not ("imie" in cols and "nazwisko" in cols):
        sys.exit("Brak kolumny z osobą: potrzebna jest „osoba” (Imię Nazwisko) albo „imię” i „nazwisko”.")
    recs = []
    for n, r in enumerate(rows, start=2):
        get = lambda k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else "")
        if "osoba" in cols:
            parts = get("osoba").split()
            first, last = (parts[0], " ".join(parts[1:])) if len(parts) >= 2 else (get("osoba"), "")
        else:
            first, last = get("imie"), get("nazwisko")
        if not first or not last:
            errors.append(f"wiersz {n}: brak imienia lub nazwiska ({get('osoba') or first!r})")
            continue
        role = parse_role(get("rola"))
        if role is None:
            errors.append(f"wiersz {n} ({first} {last}): niezrozumiała rola {get('rola')!r} (kierownik / kierowca + kierownik / tylko kierowca)")
            continue
        mn, mx = DEFAULT_MIN_H, DEFAULT_MAX_H
        if get("godziny"):
            m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", get("godziny"))
            if not m:
                errors.append(f"wiersz {n} ({first} {last}): godziny {get('godziny')!r} muszą mieć postać min-max, np. 96-144")
                continue
            mn, mx = int(m[1]), int(m[2])
        else:
            try:
                mn = int(get("min")) if get("min") else mn
                mx = int(get("max")) if get("max") else mx
            except ValueError:
                errors.append(f"wiersz {n} ({first} {last}): min/max godzin muszą być liczbami")
                continue
        if mn > mx:
            errors.append(f"wiersz {n} ({first} {last}): min godzin {mn} > max godzin {mx}")
            continue
        oj = plain(get("only_job"))
        only_job = not oj.startswith(("nie", "n", "false", "0")) if oj else True
        login = get("login").lower() or None
        if login and not re.fullmatch(auth.LOGIN_RE, login):
            errors.append(f"wiersz {n} ({first} {last}): login {login!r} musi mieć 3-80 znaków: małe litery bez polskich znaków, cyfry, . _ -")
            continue
        email = get("email") or None
        if email and not re.fullmatch(auth.EMAIL_RE, email):
            errors.append(f"wiersz {n} ({first} {last}): niepoprawny e-mail {email!r}")
            continue
        pw = get("haslo") or None
        if pw and len(pw) < auth.MIN_PASSWORD_LEN:
            errors.append(f"wiersz {n} ({first} {last}): hasło musi mieć co najmniej {auth.MIN_PASSWORD_LEN} znaków")
            continue
        recs.append({"n": n, "first": first, "last": last, "drive": role[0], "lead": role[1], "role": role[2],
                     "min": mn, "max": mx, "only_job": only_job, "login": login, "email": email, "password": pw})
    # duplikaty w pliku
    for key, label in (("name", "osoba"), ("login", "login")):
        seen = {}
        for r in recs:
            k = norm_name(r["first"], r["last"]) if key == "name" else r["login"]
            if k is None:
                continue
            if k in seen:
                errors.append(f"wiersz {r['n']}: {label} powtórzony (jest już w wierszu {seen[k]})")
            seen[k] = r["n"]
    return recs, errors


def free_login(db, base, taken):
    login, n = base, 2
    while login in taken or db.scalar(select(UserAccount.id).where(UserAccount.login == login)):
        login, n = f"{base}{n}", n + 1
    return login


def apply(db, recs):
    """Zapisuje rekordy. Zwraca (wiersze raportu, lista błędów konfliktów)."""
    users = {norm_name(u.first_name, u.last_name): u for u in db.scalars(select(User))}
    taken, report, errors = set(), [], []
    for r in recs:
        u = users.get(norm_name(r["first"], r["last"]))
        is_new = u is None
        if is_new:
            u = User(first_name=r["first"], last_name=r["last"])
            db.add(u)
        u.can_drive, u.can_lead, u.only_job, u.min_h, u.max_h = r["drive"], r["lead"], r["only_job"], r["min"], r["max"]
        acc = u.account
        if acc is None:
            login = r["login"] or free_login(db, auth.default_login(r["first"], r["last"]), taken)
            clash = db.scalar(select(UserAccount).where(UserAccount.login == login))
            if clash is not None or login in taken or login == auth.admin_login():
                errors.append(f"wiersz {r['n']} ({r['first']} {r['last']}): login {login!r} jest już zajęty")
                continue
            acc = u.account = UserAccount(login=login)
        elif r["login"] and r["login"] != acc.login:
            clash = db.scalar(select(UserAccount).where(UserAccount.login == r["login"], UserAccount.id != acc.id))
            if clash is not None or r["login"] in taken or r["login"] == auth.admin_login():
                errors.append(f"wiersz {r['n']} ({r['first']} {r['last']}): login {r['login']!r} jest już zajęty")
                continue
            acc.login = r["login"]
        taken.add(acc.login)
        if r["email"]:
            acc.email = r["email"]
        shown_pw = ""
        if r["password"]:
            acc.password_hash = auth.hash_password(r["password"])
        elif not acc.password_hash:  # nowa osoba (albo konto bez hasła) dostaje losowe hasło
            shown_pw = "".join(secrets.choice(PW_ALPHABET) for _ in range(10))
            acc.password_hash = auth.hash_password(shown_pw)
        report.append([acc.login, f"{r['first']} {r['last']}", r["role"], f"{r['min']}-{r['max']}",
                       "tak" if r["only_job"] else "nie", "nowy" if is_new else "zaktualizowany", shown_pw])
        db.flush()
    return report, errors


def delete_missing(db, recs):
    """Usuwa użytkowników, których nie ma w pliku (z dyspozycjami, zamianami, dziennikiem; konto kasuje się kaskadowo)."""
    keep = {norm_name(r["first"], r["last"]) for r in recs}
    removed = []
    for u in db.scalars(select(User)).all():
        if norm_name(u.first_name, u.last_name) in keep:
            continue
        db.query(Submission).filter(Submission.user_id == u.id).delete()
        db.query(Swap).filter((Swap.requester_id == u.id) | (Swap.partner_id == u.id)).delete()
        db.query(ScheduleEdit).filter(ScheduleEdit.user_id == u.id).delete()
        db.delete(u)
        removed.append(u.full_name)
    db.flush()
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plik", help="plik CSV albo - (stdin)")
    ap.add_argument("--dry-run", action="store_true", help="tylko pokaż, co by się stało; nic nie zapisuj")
    ap.add_argument("--sync", action="store_true",
                    help="USUŃ z bazy osoby, których nie ma w pliku (baza ma zawierać tylko osoby z pliku)")
    a = ap.parse_args()
    raw = sys.stdin.buffer.read() if a.plik == "-" else open(a.plik, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1250")  # Excel w Windows często zapisuje CSV w tym kodowaniu
    recs, errors = parse(text)
    if a.sync and not recs and not errors:
        errors = ["plik nie zawiera żadnej osoby, a --sync usunąłby wszystkich z bazy"]
    if errors:
        print("BŁĘDY W PLIKU (nic nie zapisano):", file=sys.stderr)
        print("\n".join("  - " + e for e in errors), file=sys.stderr)
        sys.exit(1)
    init_db()
    with SessionLocal() as db:
        removed = delete_missing(db, recs) if a.sync else []
        report, conflicts = apply(db, recs)
        if conflicts:
            db.rollback()
            print("BŁĘDY (nic nie zapisano):", file=sys.stderr)
            print("\n".join("  - " + e for e in conflicts), file=sys.stderr)
            sys.exit(1)
        if a.dry_run:
            db.rollback()
        else:
            db.commit()
    print(f"{'PODGLĄD (nic nie zapisano)' if a.dry_run else 'ZAPISANO'}: "
          f"{sum(r[5] == 'nowy' for r in report)} nowych, {sum(r[5] == 'zaktualizowany' for r in report)} zaktualizowanych"
          + (f", {'DO USUNIĘCIA' if a.dry_run else 'USUNIĘTO'}: {len(removed)}" if a.sync else "") + "\n")
    if a.sync and removed:
        print(f"{'Zostałyby usunięte' if a.dry_run else 'Usunięte'} osoby spoza pliku ({len(removed)}): {', '.join(removed)}\n")
    w = [max(len(str(r[i])) for r in [["login", "osoba", "rola", "godziny", "jedyne miejsce", "status", "hasło"]] + report) for i in range(7)]
    for r in [["login", "osoba", "rola", "godziny", "jedyne miejsce", "status", "hasło"]] + report:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    if any(r[6] for r in report) and not a.dry_run:
        print("\nHasła z ostatniej kolumny są pokazane tylko teraz (w bazie jest sam hash). Przekaż je osobom; "
              "każdy może je zmienić w „Moje konto”.")
    elif any(r[6] for r in report):
        print("\nPodgląd: hasła nie zostały zapisane (przy zapisie zostaną wylosowane nowe).")


if __name__ == "__main__":
    main()
