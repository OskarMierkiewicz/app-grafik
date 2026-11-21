"""Jednorazowa migracja: hasła z dawnej kolumny users.password_hash → tabela user_accounts."""
from sqlalchemy import inspect, text

from .auth import slug
from .db import engine


def migrate_legacy_passwords():
    if "password_hash" not in {c["name"] for c in inspect(engine).get_columns("users")}:
        return  # świeża baza, nic do przeniesienia
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, first_name, last_name, password_hash FROM users "
                                 "WHERE password_hash IS NOT NULL")).all()
        have = {r[0] for r in conn.execute(text("SELECT user_id FROM user_accounts"))}
        used = {r[0] for r in conn.execute(text("SELECT login FROM user_accounts"))}
        for uid, first, last, pw in rows:
            if uid in have:
                continue
            base = f"{slug(first)}.{slug(last)}"
            login, n = base, 2
            while login in used:
                login, n = f"{base}{n}", n + 1
            used.add(login)
            conn.execute(text("INSERT INTO user_accounts (user_id, login, password_hash) VALUES (:u, :l, :p)"),
                         {"u": uid, "l": login, "p": pw})
