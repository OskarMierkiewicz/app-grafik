"""Logowanie: konto administratora (z env) i konta użytkowników (z tabeli users), sesje w ciasteczku.

Login użytkownika jest wyliczany z imienia i nazwiska: "Łukasz Żak" → "lukasz.zak".
Hasła użytkowników ustawia administrator (zakładka Użytkownicy); użytkownik może je zmienić w „Moje konto".
"""
import hashlib
import hmac
import os
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, UserAccount

MIN_PASSWORD_LEN = 8


# --------------------------------------------------------------------------
# Hasła
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-constant-time")


# --------------------------------------------------------------------------
# Login użytkownika i konto administratora
# --------------------------------------------------------------------------
def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = "-".join(s.casefold().split())
    return re.sub(r"[^a-z0-9-]", "", s)  # np. "O'Brien" → "obrien", żeby login pasował do LOGIN_RE


def default_login(first_name: str, last_name: str) -> str:
    """Domyślny login z imienia i nazwiska: "Łukasz Żak" → "lukasz.zak"."""
    return f"{slug(first_name)}.{slug(last_name)}"


LOGIN_RE = r"[a-z0-9._-]{3,80}"
EMAIL_RE = r"[^@\s]+@[^@\s]+\.[^@\s]+"


def admin_login() -> str:
    return os.getenv("ADMIN_LOGIN", "admin").strip().lower()


_generated_admin_pw = None


def admin_password() -> str:
    """ADMIN_PASSWORD (lub stare APP_PASSWORD). Gdy brak: losowe hasło wypisane w logu przy starcie."""
    global _generated_admin_pw
    pw = os.getenv("ADMIN_PASSWORD") or os.getenv("APP_PASSWORD")
    if pw:
        return pw
    if _generated_admin_pw is None:
        _generated_admin_pw = secrets.token_urlsafe(12)
        print(f"[UWAGA] Nie ustawiono ADMIN_PASSWORD. Tymczasowe hasło administratora ({admin_login()}): "
              f"{_generated_admin_pw}", flush=True)
    return _generated_admin_pw


def find_account(db: Session, login: str) -> UserAccount | None:
    return db.query(UserAccount).filter(UserAccount.login == login.strip().lower()).one_or_none()


# --------------------------------------------------------------------------
# Ograniczenie prób logowania (w pamięci procesu)
# --------------------------------------------------------------------------
_fails: dict[str, list[float]] = {}
MAX_FAILS, WINDOW = 5, 300.0


def throttled(key: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < WINDOW]
    _fails[key] = recent
    return len(recent) >= MAX_FAILS


def register_fail(key: str):
    if len(_fails) > 10_000:  # ochrona pamięci przed zalewem różnych loginów
        now = time.time()
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > WINDOW]:
            _fails.pop(k, None)
    _fails.setdefault(key, []).append(time.time())


def clear_fails(key: str):
    _fails.pop(key, None)


# --------------------------------------------------------------------------
# Zalogowany podmiot i zależności FastAPI
# --------------------------------------------------------------------------
@dataclass
class Principal:
    role: str  # "admin" | "user"
    name: str
    user: User | None = None

    @property
    def is_admin(self):
        return self.role == "admin"


def session_login(request: Request, role: str, user: User | None = None):
    request.session.clear()
    request.session["role"] = role
    if user is not None:
        request.session["uid"] = user.id
        pw = user.account.password_hash if user.account else ""
        request.session["pwh"] = (pw or "")[-16:]  # zmiana hasła unieważnia sesję


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    s = request.session
    p = None
    if s.get("role") == "admin":
        p = Principal("admin", admin_login())
    elif s.get("role") == "user":
        u = db.get(User, s.get("uid") or 0)
        acc = u.account if u else None
        if u and u.active and acc and acc.password_hash and acc.password_hash[-16:] == s.get("pwh"):
            p = Principal("user", u.full_name, u)
    request.state.principal = p
    return p


def login_required(p: Principal | None = Depends(get_principal)) -> Principal:
    if p is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return p


def admin_required(p: Principal = Depends(login_required)) -> Principal:
    if not p.is_admin:
        raise HTTPException(status_code=403, detail="Tylko dla administratora")
    return p
