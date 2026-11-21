"""Hurtowe ustawianie nowych haseł użytkowników (np. gdy hasła z importu nie zostały zapisane).

  docker compose exec -T web python -m app.reset_passwords --all > hasla.csv          # nowe losowe hasła wszystkim
  docker compose exec -T web python -m app.reset_passwords --login jan.kowalski ewa.samul > hasla.csv
  docker compose exec -T web python -m app.reset_passwords --all --same-password 'Start2027!'  # to samo hasło wszystkim

Na standardowe wyjście trafia tylko CSV (login;osoba;hasło), więc `> hasla.csv` zapisuje czysty plik do przekazania osobom.
Komunikaty idą na stderr. W bazie zostaje sam hash, więc hasła nie da się później odczytać; w razie potrzeby uruchom ponownie.
Każdy może zmienić swoje hasło w „Moje konto”. Stare sesje osób ze zmienionym hasłem są unieważnione.
"""
import argparse
import csv
import secrets
import sys

from sqlalchemy import select

from . import auth
from .db import SessionLocal, init_db
from .models import User, UserAccount

PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez 0/O, 1/l/I


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="wszystkie aktywne osoby z kontem")
    g.add_argument("--login", nargs="+", metavar="LOGIN", help="tylko wskazane loginy")
    ap.add_argument("--same-password", metavar="HASŁO", help="to samo hasło dla wszystkich zamiast losowych (min. 8 znaków)")
    a = ap.parse_args()
    if a.same_password is not None and len(a.same_password) < auth.MIN_PASSWORD_LEN:
        sys.exit(f"Hasło musi mieć co najmniej {auth.MIN_PASSWORD_LEN} znaków.")

    init_db()
    with SessionLocal() as db:
        q = select(UserAccount).join(User, UserAccount.user_id == User.id).order_by(User.last_name, User.first_name)
        if a.all:
            accs = db.scalars(q.where(User.active)).all()
        else:
            wanted = {x.strip().lower() for x in a.login}
            accs = db.scalars(q.where(UserAccount.login.in_(wanted))).all()
            missing = wanted - {x.login for x in accs}
            if missing:
                sys.exit("Nie ma kont o loginach: " + ", ".join(sorted(missing)) + " (nic nie zmieniono)")
        if not accs:
            sys.exit("Brak kont do zmiany.")
        out = csv.writer(sys.stdout, delimiter=";", lineterminator="\n")
        out.writerow(["login", "osoba", "hasło"])
        for acc in accs:
            pw = a.same_password or "".join(secrets.choice(PW_ALPHABET) for _ in range(10))
            acc.password_hash = auth.hash_password(pw)
            out.writerow([acc.login, acc.user.full_name, pw])
        db.commit()
    print(f"Ustawiono nowe hasła: {len(accs)}. Zapisz je teraz (np. > hasla.csv): w bazie jest tylko hash.", file=sys.stderr)


if __name__ == "__main__":
    main()
