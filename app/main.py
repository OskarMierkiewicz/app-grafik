import datetime as dt
import hashlib
import os
import re
import secrets
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import auth, law, roles, rules, solver, swaps
from .auth import Principal, admin_required, login_required
from .db import get_db, init_db
from .migrate import migrate_legacy_passwords
from .models import DEFAULT_MAX_H, DEFAULT_MIN_H, Schedule, ScheduleEdit, Submission, Swap, User, UserAccount
from .xlsx_io import MAX_UPLOAD_BYTES, FormError, make_form, read_form, write_schedule

BASE = Path(__file__).parent
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
APP_NAME = os.getenv("APP_NAME", "Grafik - Lux Med Wileńska 44")  # nazwa w nagłówku i tytule karty
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["zip"] = lambda a, b: zip(a, b)
templates.env.globals["shift_label"] = swaps.label
templates.env.globals["app_name"] = APP_NAME


def _static_version() -> str:
    """Skrót zawartości plików statycznych: po każdej zmianie CSS/JS adres ma nowy ?v=..., więc przeglądarka nie trzyma starej wersji."""
    h = hashlib.md5()
    for f in sorted((BASE / "static").glob("*")):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()[:10]


STATIC_V = _static_version()
templates.env.globals["static"] = lambda name: f"/static/{name}?v={STATIC_V}"
templates.env.filters.update(role_icon=roles.icon, role_name=roles.name, role_full=roles.full, role_tags=roles.tags,
                             user_role=roles.user_code)


@asynccontextmanager
async def lifespan(app):
    init_db()
    migrate_legacy_passwords()
    auth.admin_password()  # przy braku ADMIN_PASSWORD wypisze tymczasowe hasło w logu
    yield


# /docs i /openapi.json wyłączone: nie ujawniamy listy endpointów niezalogowanym
app = FastAPI(title=APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY") or secrets.token_hex(32),  # bez SECRET_KEY sesje wygasają po restarcie
    same_site="lax",
    https_only=os.getenv("SESSION_HTTPS_ONLY", "0") == "1",
    max_age=14 * 24 * 3600,
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def norm(s: str) -> str:
    """Normalizacja imienia/nazwiska do porównań: bez ogonków, wielkości liter i nadmiarowych spacji."""
    s = unicodedata.normalize("NFKD", s.replace("ł", "l").replace("Ł", "L"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


def default_month() -> str:
    t = rules.today()  # data w strefie Europe/Warsaw, a nie systemowa (kontener ma UTC)
    y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    return f"{y}-{m:02d}"


def open_month() -> str:
    """Miesiąc, na który zapisy są teraz otwarte (patrz rules.open_month)."""
    return rules.open_month()


def canon_month(month: str | None) -> str | None:
    """Kanoniczna postać RRRR-MM (np. "2027-1" → "2027-01") albo None, gdy format jest zły."""
    try:
        y, m = solver.parse_month(month or "")
        return f"{y}-{m:02d}"
    except ValueError:
        return None


def valid_month(month: str | None) -> str:
    return canon_month(month) or default_month()


def read_upload(f: UploadFile) -> bytes:
    """Czyta plik z limitem (czytamy o 1 bajt więcej, żeby read_form mógł odrzucić zbyt duży)."""
    return f.file.read(MAX_UPLOAD_BYTES + 1)


def localdt(value, fmt="%d.%m.%Y %H:%M"):
    """Czas z bazy (UTC bez strefy) → czas lokalny Europe/Warsaw."""
    if value is None:
        return ""
    from zoneinfo import ZoneInfo
    return value.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(os.getenv("TZ_NAME", "Europe/Warsaw"))).strftime(fmt)


templates.env.filters["localdt"] = localdt


def render(request, name, **ctx):
    ctx.setdefault("principal", getattr(request.state, "principal", None))
    return templates.TemplateResponse(request, name, ctx)


def send(url, msg):
    return RedirectResponse(f"{url}{'&' if '?' in url else '?'}msg={quote(msg)}", status_code=303)


# --------------------------------------------------------------------------
# Logowanie
# --------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, p: Principal | None = Depends(auth.get_principal)):
    if p:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", principal=None)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, login: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}|{login.strip().lower()}"
    if auth.throttled(key):
        return render(request, "login.html", principal=None, error="Za dużo nieudanych prób. Spróbuj za kilka minut.")
    lg = login.strip().lower()
    if lg == auth.admin_login() and secrets.compare_digest(password.encode(), auth.admin_password().encode()):
        auth.session_login(request, "admin")
        auth.clear_fails(key)
        return RedirectResponse("/", status_code=303)
    acc = auth.find_account(db, lg)
    u = acc.user if acc else None
    # zawsze liczymy hash (też dla nieistniejącego loginu), żeby czas odpowiedzi nie zdradzał, czy login istnieje
    valid = auth.verify_password(password, acc.password_hash if acc and acc.password_hash else auth.DUMMY_HASH)
    if u and acc.password_hash and u.active and valid:
        auth.session_login(request, "user", u)
        auth.clear_fails(key)
        return RedirectResponse("/", status_code=303)
    auth.register_fail(key)
    return render(request, "login.html", principal=None, error="Błędny login lub hasło.")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def home(p: Principal = Depends(login_required)):
    return RedirectResponse("/dyspozycje", status_code=303)


@app.get("/konto", response_class=HTMLResponse)
def account(request: Request, msg: str | None = None, p: Principal = Depends(login_required)):
    return render(request, "konto.html", msg=msg)


@app.post("/konto", response_class=HTMLResponse)
def account_change(request: Request, current: str = Form(...), new: str = Form(...), repeat: str = Form(...),
                   db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    if p.is_admin:
        raise HTTPException(403, "Hasło administratora ustawia się w zmiennej ADMIN_PASSWORD")
    u, acc = p.user, p.user.account
    if not auth.verify_password(current, acc.password_hash):
        return render(request, "konto.html", error="Obecne hasło jest niepoprawne.")
    if new != repeat:
        return render(request, "konto.html", error="Nowe hasła nie są takie same.")
    if len(new) < auth.MIN_PASSWORD_LEN:
        return render(request, "konto.html", error=f"Hasło musi mieć co najmniej {auth.MIN_PASSWORD_LEN} znaków.")
    acc.password_hash = auth.hash_password(new)
    db.commit()
    auth.session_login(request, "user", u)  # odświeża sesję pod nowe hasło
    return send("/konto", "Hasło zmienione.")


@app.post("/konto/email", response_class=HTMLResponse)
def account_email(request: Request, email: str = Form(""), db: Session = Depends(get_db),
                  p: Principal = Depends(login_required)):
    if p.is_admin:
        raise HTTPException(403, "Administrator nie ma konta w bazie")
    email = email.strip()
    if email and not re.fullmatch(auth.EMAIL_RE, email):
        return render(request, "konto.html", error="Niepoprawny adres e-mail.")
    p.user.account.email = email or None
    db.commit()
    return send("/konto", "Adres e-mail zapisany.")


# --------------------------------------------------------------------------
# Zapis dyspozycji (wspólne dla użytkownika i administratora)
# --------------------------------------------------------------------------
def save_submission(db: Session, u: User, form: dict, filename: str, *, user_mode: bool = False) -> str:
    month = form["month"]
    if not u.active:
        raise FormError(f"użytkownik „{u.full_name}” jest nieaktywny")
    mn = form["min_h"] if form["min_h"] is not None else u.min_h
    mx = form["max_h"] if form["max_h"] is not None else u.max_h
    if mn > mx:
        raise FormError(f"min godzin {mn} > max godzin {mx} (po uwzględnieniu wartości domyślnych)")
    oh = form["other_hours"]
    if u.only_job and oh:
        raise FormError("podano godziny w innych miejscach, ale w bazie jest only_job=true (jedyne miejsce pracy); "
                        "administrator musi zmienić to w zakładce Użytkownicy")
    if not u.only_job and oh is None and law.law_active(month):
        raise FormError("w bazie jest only_job=false (praca także gdzie indziej): podaj godziny w innych miejscach "
                        "(0, jeśli w tym miesiącu nie pracujesz gdzie indziej)")
    if user_mode:
        reason = rules.lock_reason(db, month)
        if reason:
            raise FormError(f"{reason}. Zmianę dyspozycji zgłoś administratorowi")
    _, _, law_note = law.apply_limit(month, u.only_job, oh, mx, mn)
    sub = db.scalar(select(Submission).where(Submission.user_id == u.id, Submission.month == month))
    replaced = sub is not None
    if sub is None:
        sub = Submission(user_id=u.id, month=month)
        db.add(sub)
    sub.min_h, sub.max_h, sub.other_hours = form["min_h"], form["max_h"], oh
    sub.avail = {str(d): v for d, v in form["avail"].items()}
    sub.updated_at = dt.datetime.utcnow()
    sub.source = filename[:255]
    db.commit()
    return (f"{len(form['avail'])} dni dostępności, godziny {mn}–{mx}" + (f", {law_note}" if law_note else "")
            + (" (zastąpiono wcześniejszą)" if replaced else ""))


# --------------------------------------------------------------------------
# Dla wszystkich zalogowanych: dyspozycje, własny plik, grafiki
# --------------------------------------------------------------------------
def month_marks(db: Session) -> list[str]:
    """Miesiące, w których są jakieś dyspozycje lub grafiki (kropka w wybieraczu miesiąca)."""
    found = {m for (m,) in db.execute(select(Submission.month).distinct())} | {m for (m,) in db.execute(select(Schedule.month).distinct())}
    return sorted(found)


MONTH_NOM = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"]
MONTH_LOC = ["styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu", "lipcu", "sierpniu", "wrześniu", "październiku", "listopadzie", "grudniu"]
MONTH_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


def month_stats(month: str, done: int, total: int) -> dict:
    """Statystyki miesiąca: godziny do obsadzenia (2 osoby × 24 h × dni), godziny świąteczne (bez niedziel), % dyspozycji."""
    y, m = solver.parse_month(month)
    ndays, _, hol = solver.calendar_info(y, m)
    per_day = solver.PER_SHIFT * 2 * solver.HOURS  # 2 osoby × 2 zmiany po 12 h = 2 osoby × 24 h = 48 h na dobę
    fmt = lambda n: f"{n:,}".replace(",", "\u00a0")
    counted, sundays = [], []
    for d, name in sorted(hol.items()):
        wd = dt.date(y, m, d).weekday()
        item = {"d": d, "name": name, "wd": solver.DAY_NAMES[wd], "mon": MONTH_SHORT[m - 1]}
        (sundays if wd == 6 else counted).append(item)
    return {"month_name": f"{MONTH_NOM[m - 1]} {y}", "month_loc": f"{MONTH_LOC[m - 1]} {y}", "ndays": ndays, "per_day": per_day,
            "total_hours": fmt(ndays * per_day), "holidays": counted, "sunday_holidays": sundays,
            "holiday_hours": fmt(len(counted) * per_day), "pct": round(100 * done / total) if total else 0,
            "done": done, "total": total}


def dyspozycje_ctx(db: Session, month: str, p: Principal, **extra):
    users = db.scalars(select(User).where(User.active).order_by(User.last_name, User.first_name)).all()
    subs = {s.user_id: s for s in db.scalars(select(Submission).where(Submission.month == month))}
    rows = [(u, subs.get(u.id)) for u in users]
    published = db.scalar(select(Schedule).where(Schedule.month == month, Schedule.published).limit(1))
    done = sum(1 for _, s in rows if s)
    return {"month": month, "rows": rows, "done": done, "total": len(rows), "stats": month_stats(month, done, len(rows)),
            "published": published, "mine": subs.get(p.user.id) if p.user else None,
            "deadline": rules.deadline_for(month), "lock": rules.lock_reason(db, month), "marks": month_marks(db), **extra}


@app.get("/dyspozycje", response_class=HTMLResponse)
def dyspozycje(request: Request, month: str | None = None, msg: str | None = None,
               db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    return render(request, "dyspozycje.html", **dyspozycje_ctx(db, valid_month(month or open_month()), p, msg=msg))


@app.get("/moj-formularz")
def my_form(month: str, p: Principal = Depends(login_required)):
    """Szablon dla jednego użytkownika, z jego imieniem i nazwiskiem; plik nazywa się RRRR-MM.xlsx."""
    month = canon_month(month)
    if not month:
        raise HTTPException(400, "Zły format miesiąca (oczekiwane RRRR-MM)")
    data = make_form(month, p.user.first_name if p.user else "", p.user.last_name if p.user else "")
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{month}.xlsx"'})


@app.post("/moja-dyspozycja", response_class=HTMLResponse)
def my_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
              p: Principal = Depends(login_required)):
    if p.is_admin:
        raise HTTPException(403, "Administrator wgrywa pliki w panelu administratora")
    u = p.user
    fname = os.path.basename(file.filename or "").strip()
    month, result = default_month(), None
    try:
        m = re.fullmatch(r"(\d{4})-(\d{2})\.xlsx", fname, re.I)
        if not m:
            raise FormError("nazwa pliku musi mieć postać RRRR-MM.xlsx (np. 2027-01.xlsx), czyli miesiąc, którego dotyczy dyspozycja")
        month = f"{m[1]}-{m[2]}"
        try:
            solver.parse_month(month)
        except ValueError as e:
            raise FormError(str(e))
        form = read_form(read_upload(file))
        if form["month"] != month:
            raise FormError(f"nazwa pliku wskazuje miesiąc {month}, a w środku pliku jest {form['month']}")
        if norm(f"{form['first']} {form['last']}") != norm(u.full_name):
            raise FormError(f"w pliku jest „{form['first']} {form['last']}”, a jesteś zalogowany jako „{u.full_name}”. "
                            "Pobierz swój formularz przyciskiem „Pobierz mój formularz”")
        note = save_submission(db, u, form, fname, user_mode=True)
        result = {"ok": True, "msg": f"Zapisano dyspozycję na {month}: {note}"}
    except FormError as e:
        db.rollback()
        result = {"ok": False, "msg": f"{fname or 'plik'}: {e}"}
    return render(request, "dyspozycje.html", **dyspozycje_ctx(db, month, p, result=result))


@app.get("/grafiki", response_class=HTMLResponse)
def schedules_list(request: Request, db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    q = select(Schedule).order_by(Schedule.month.desc(), Schedule.id.desc())
    if not p.is_admin:
        q = q.where(Schedule.published)
    rows = db.scalars(q).all()
    cur = default_month()
    return render(request, "grafiki.html", schedules=rows, cur=cur)


def get_visible_schedule(db: Session, sid: int, p: Principal) -> Schedule:
    sch = db.get(Schedule, sid)
    if not sch or (not p.is_admin and not sch.published):
        raise HTTPException(404, "Nie ma takiego grafiku")
    return sch


@app.get("/schedules/{sid}", response_class=HTMLResponse)
def schedule_view(request: Request, sid: int, msg: str | None = None, db: Session = Depends(get_db),
                  p: Principal = Depends(login_required)):
    sch = get_visible_schedule(db, sid, p)
    done = db.scalars(select(Swap).where(Swap.schedule_id == sid, Swap.status == "applied").order_by(Swap.decided_at)).all()
    edits = (db.scalars(select(ScheduleEdit).where(ScheduleEdit.schedule_id == sid).order_by(ScheduleEdit.id)).all()
             if p.is_admin else [])
    return render(request, "schedule.html", sch=sch, rep=sch.report, msg=msg, applied_swaps=done, edits=edits)


@app.get("/schedules/{sid}/xlsx")
def schedule_xlsx(sid: int, db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    sch = get_visible_schedule(db, sid, p)
    data = sch.xlsx if p.is_admin else write_schedule(sch.report, public=True)  # bez danych prywatnych kolegów
    return Response(data, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="grafik_{sch.month}_{sch.id}.xlsx"'})


# --------------------------------------------------------------------------
# Panel administratora: dyspozycje na miesiąc, wgrywanie, generowanie
# --------------------------------------------------------------------------
def index_ctx(db: Session, month: str, **extra):
    month = canon_month(month) or month
    try:
        solver.parse_month(month)
    except ValueError as e:
        month = default_month()
        extra.setdefault("error", str(e))
    subs = db.execute(
        select(Submission, User).join(User, Submission.user_id == User.id)
        .where(Submission.month == month).order_by(User.last_name, User.first_name)
    ).all()
    submitted = {u.id for _, u in subs}
    missing = [u for u in db.scalars(select(User).where(User.active).order_by(User.last_name, User.first_name)) if u.id not in submitted]
    schedules = db.scalars(select(Schedule).where(Schedule.month == month).order_by(Schedule.id.desc()).limit(10)).all()
    return {"month": month, "subs": subs, "missing": missing, "schedules": schedules, "marks": month_marks(db), **extra}


@app.get("/admin", response_class=HTMLResponse)
def index(request: Request, month: str | None = None, msg: str | None = None, db: Session = Depends(get_db),
          p: Principal = Depends(admin_required)):
    return render(request, "index.html", **index_ctx(db, month or default_month(), msg=msg))


@app.get("/formularz")
def formularz(month: str, p: Principal = Depends(admin_required)):
    month = canon_month(month)
    if not month:
        raise HTTPException(400, "Zły format miesiąca (oczekiwane RRRR-MM)")
    data = make_form(month)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="dyspozycja_{month}.xlsx"'})


@app.post("/upload", response_class=HTMLResponse)
def upload(request: Request, month: str = Form(...), files: list[UploadFile] = File(...),
           db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    users = {norm(u.full_name): u for u in db.scalars(select(User))}
    results, last_month = [], month
    for f in files:
        if not f.filename:
            continue
        try:
            form = read_form(read_upload(f))
            u = users.get(norm(f"{form['first']} {form['last']}"))
            if u is None:
                raise FormError(f"nie ma użytkownika „{form['first']} {form['last']}” w bazie (dodaj go w zakładce Użytkownicy)")
            note = save_submission(db, u, form, f.filename)
            last_month = form["month"]
            results.append({"file": f.filename, "ok": True, "msg": f"{u.full_name}: {note}"})
        except FormError as e:
            db.rollback()
            results.append({"file": f.filename, "ok": False, "msg": str(e)})
    return render(request, "index.html", **index_ctx(db, last_month, results=results))


@app.post("/submissions/{sid}/delete")
def delete_submission(sid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    sub = db.get(Submission, sid)
    month = sub.month if sub else default_month()
    if sub:
        db.delete(sub)
        db.commit()
    return RedirectResponse(f"/admin?month={month}", status_code=303)


@app.post("/generate", response_class=HTMLResponse)
def generate(request: Request, month: str = Form(...), czas: int = Form(30), db: Session = Depends(get_db),
             p: Principal = Depends(admin_required)):
    try:
        year, mon = solver.parse_month(month)
    except ValueError as e:
        return render(request, "index.html", **index_ctx(db, default_month(), error=str(e)))
    month = f"{year}-{mon:02d}"
    rows = db.execute(
        select(Submission, User).join(User, Submission.user_id == User.id)
        .where(Submission.month == month, User.active).order_by(User.last_name, User.first_name)
    ).all()
    if len(rows) < 2:
        return render(request, "index.html", **index_ctx(db, month, error="Potrzebne są dyspozycje co najmniej dwóch osób."))

    persons, avail, errors = [], [], []
    for sub, u in rows:
        mn = sub.min_h if sub.min_h is not None else u.min_h
        mx = sub.max_h if sub.max_h is not None else u.max_h
        if mn > mx:
            errors.append(f"{u.full_name}: min {mn} > max {mx}")
        try:
            mn, mx, law_note = law.apply_limit(month, u.only_job, sub.other_hours, mx, mn)
        except ValueError:
            errors.append(f"{u.full_name}: only_job=false, ale brak godzin w innych miejscach (wgraj formularz ponownie)")
            continue
        persons.append(solver.Person(u.id, u.full_name, u.can_drive, u.can_lead, mn, mx, u.saldo, law_note))
        avail.append({int(d): v for d, v in sub.avail.items()})
    if errors:
        return render(request, "index.html", **index_ctx(db, month, error="; ".join(errors)))

    ndays, off, _ = solver.calendar_info(year, mon)
    pre = solver.precheck(persons, avail, ndays)
    try:
        assign, meta = solver.solve(persons, avail, ndays, off, max(5, min(czas, 300)))
    except RuntimeError as e:
        return render(request, "index.html", **index_ctx(db, month, error=str(e)))
    missing = [u.full_name for u in db.scalars(select(User).where(User.active).order_by(User.last_name))
               if u.id not in {pp.uid for pp in persons}]
    report = solver.build_report(month, persons, avail, assign, meta, pre, missing)
    sch = Schedule(month=month, report=report, xlsx=write_schedule(report))
    db.add(sch)
    db.commit()
    return RedirectResponse(f"/schedules/{sch.id}", status_code=303)


@app.post("/schedules/{sid}/publish")
def schedule_publish(sid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    """Publikuje grafik dla użytkowników (jeden opublikowany na miesiąc; poprzedni jest wycofywany)."""
    sch = db.get(Schedule, sid)
    if not sch:
        raise HTTPException(404, "Nie ma takiego grafiku")
    db.query(Schedule).filter(Schedule.month == sch.month).update({"published": False})
    sch.published = True
    db.commit()
    return send(f"/schedules/{sid}", "Opublikowano: grafik widzą teraz wszyscy zalogowani użytkownicy.")


@app.post("/schedules/{sid}/unpublish")
def schedule_unpublish(sid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    sch = db.get(Schedule, sid)
    if not sch:
        raise HTTPException(404, "Nie ma takiego grafiku")
    sch.published = False
    db.commit()
    return send(f"/schedules/{sid}", "Wycofano publikację.")


@app.post("/schedules/{sid}/apply-saldo")
def apply_saldo(sid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    """Zapisuje nowe saldo uciążliwości w bazie (raz na miesiąc)."""
    sch = db.get(Schedule, sid)
    if not sch:
        raise HTTPException(404, "Nie ma takiego grafiku")
    other = db.scalar(select(Schedule).where(Schedule.month == sch.month, Schedule.saldo_applied))
    if sch.saldo_applied or other:
        return send(f"/schedules/{sid}", "Saldo dla tego miesiąca zostało już zatwierdzone.")
    for pp in sch.report["people"]:
        u = db.get(User, pp["uid"])
        if u:
            u.saldo += pp["saldo_new"] - pp["saldo_old"]  # przyrost z tego grafiku, nie nadpisanie
    sch.saldo_applied = True
    db.commit()
    return send(f"/schedules/{sid}", "Zatwierdzono: saldo użytkowników zaktualizowane.")


@app.post("/schedules/{sid}/delete")
def schedule_delete(sid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    sch = db.get(Schedule, sid)
    month = sch.month if sch else default_month()
    if sch:
        db.query(Swap).filter(Swap.schedule_id == sid).delete()
        db.query(ScheduleEdit).filter(ScheduleEdit.schedule_id == sid).delete()
        db.delete(sch)
        db.commit()
    return RedirectResponse(f"/admin?month={month}", status_code=303)


# --------------------------------------------------------------------------
# Użytkownicy (administrator)
# --------------------------------------------------------------------------
def users_ctx(db: Session, **extra):
    users = db.scalars(select(User).order_by(User.last_name, User.first_name)).all()
    return {"users": users, "def_min": DEFAULT_MIN_H, "def_max": DEFAULT_MAX_H, **extra}


def validate_user(first, last, drive, lead, mn, mx):
    if not first.strip() or not last.strip():
        return "Imię i nazwisko są wymagane."
    if not (drive or lead):
        return "Użytkownik musi być kierowcą lub kierownikiem."
    if mn < 0 or mn > mx:
        return "Min godzin musi być ≥ 0 i ≤ max godzin."
    return None


def validate_account(db: Session, login: str, email: str, password: str, exclude_account_id: int | None = None):
    if not re.fullmatch(auth.LOGIN_RE, login):
        return "Login: 3-80 znaków, małe litery bez polskich znaków, cyfry oraz . _ -"
    if login == auth.admin_login():
        return "Ten login jest zarezerwowany dla administratora."
    if db.scalar(select(UserAccount.id).where(UserAccount.login == login, UserAccount.id != (exclude_account_id or 0))):
        return "Taki login już istnieje."
    if email and not re.fullmatch(auth.EMAIL_RE, email):
        return "Niepoprawny adres e-mail."
    if password and len(password) < auth.MIN_PASSWORD_LEN:
        return f"Hasło musi mieć co najmniej {auth.MIN_PASSWORD_LEN} znaków."
    return None


def free_login(db: Session, first: str, last: str) -> str:
    base = auth.default_login(first, last)
    login, n = base, 2
    while db.scalar(select(UserAccount.id).where(UserAccount.login == login)):
        login, n = f"{base}{n}", n + 1
    return login


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, msg: str | None = None, db: Session = Depends(get_db),
               p: Principal = Depends(admin_required)):
    return render(request, "users.html", **users_ctx(db, msg=msg))


@app.post("/users", response_class=HTMLResponse)
def user_create(request: Request, first_name: str = Form(...), last_name: str = Form(...),
                can_drive: str | None = Form(None), can_lead: str | None = Form(None), only_job: str | None = Form(None),
                min_h: int = Form(DEFAULT_MIN_H), max_h: int = Form(DEFAULT_MAX_H), login: str = Form(""),
                email: str = Form(""), password: str = Form(""),
                db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    login, email = login.strip().lower(), email.strip()
    err = validate_user(first_name, last_name, bool(can_drive), bool(can_lead), min_h, max_h)
    if not err:
        if norm(f"{first_name} {last_name}") in {norm(u.full_name) for u in db.scalars(select(User))}:
            err = "Taki użytkownik już istnieje."
    if not err:
        login = login or free_login(db, first_name, last_name)
        err = validate_account(db, login, email, password)
    if err:
        return render(request, "users.html", **users_ctx(db, error=err))
    u = User(first_name=first_name.strip(), last_name=last_name.strip(), can_drive=bool(can_drive),
             can_lead=bool(can_lead), only_job=bool(only_job), min_h=min_h, max_h=max_h)
    u.account = UserAccount(login=login, email=email or None,
                            password_hash=auth.hash_password(password) if password else None)
    db.add(u)
    db.commit()
    return RedirectResponse("/users", status_code=303)


@app.post("/users/{uid}", response_class=HTMLResponse)
def user_update(request: Request, uid: int, first_name: str = Form(...), last_name: str = Form(...),
                can_drive: str | None = Form(None), can_lead: str | None = Form(None), active: str | None = Form(None),
                only_job: str | None = Form(None), min_h: int = Form(...), max_h: int = Form(...),
                saldo: float = Form(0.0), login: str = Form(""), email: str = Form(""), new_password: str = Form(""),
                db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Nie ma takiego użytkownika")
    login, email = login.strip().lower(), email.strip()
    err = validate_user(first_name, last_name, bool(can_drive), bool(can_lead), min_h, max_h)
    if not err:
        login = login or (u.account.login if u.account else free_login(db, first_name, last_name))
        err = validate_account(db, login, email, new_password, u.account.id if u.account else None)
    if err:
        return render(request, "users.html", **users_ctx(db, error=f"{u.full_name}: {err}"))
    u.first_name, u.last_name = first_name.strip(), last_name.strip()
    u.can_drive, u.can_lead, u.active = bool(can_drive), bool(can_lead), bool(active)
    u.only_job = bool(only_job)
    u.min_h, u.max_h, u.saldo = min_h, max_h, saldo
    if u.account is None:
        u.account = UserAccount(login=login)
    u.account.login, u.account.email = login, email or None
    if new_password:
        u.account.password_hash = auth.hash_password(new_password)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render(request, "users.html", **users_ctx(db, error="Taki użytkownik już istnieje."))
    return send("/users", f"Zapisano: {u.full_name}" + (" (nowe hasło)" if new_password else ""))


@app.post("/users/{uid}/delete")
def user_delete(uid: int, db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    u = db.get(User, uid)
    if u:
        db.query(Submission).filter(Submission.user_id == uid).delete()
        db.query(Swap).filter((Swap.requester_id == uid) | (Swap.partner_id == uid)).delete()
        db.query(ScheduleEdit).filter(ScheduleEdit.user_id == uid).delete()
        db.delete(u)  # konto (user_accounts) usuwa się kaskadowo
        db.commit()
    return RedirectResponse("/users", status_code=303)


# --------------------------------------------------------------------------
# Zamiany zmian
# --------------------------------------------------------------------------
def parse_shift(val: str | None):
    """'5-D' -> (5, 'D'); pusty -> None."""
    if not val:
        return None
    try:
        d, s = val.split("-")
        if s not in ("D", "N"):
            raise ValueError
        return int(d), s
    except ValueError:
        raise HTTPException(400, "Niepoprawna zmiana")


def my_shift_options(rep, uid, *, future_only=True):
    """Zmiany osoby jako lista (dzień, D/N); dla użytkownika tylko przyszłe lub dzisiejsze."""
    pp = swaps.person(rep, uid)
    if not pp:
        return []
    today = rules.today()
    out = []
    for d in sorted(int(x) for x in pp["assign"]):
        if future_only and swaps.shift_date(rep["month"], d) < today:
            continue
        out += [(d, s) for s in pp["assign"][str(d)]]
    return out


def swap_context(db: Session, p: Principal, month: str | None, partner: int | None, a: int | None, b: int | None):
    months = [m for (m,) in db.execute(select(Schedule.month).where(Schedule.published).distinct().order_by(Schedule.month))]
    cur = default_month()
    month = canon_month(month) if month else None
    if month not in months:
        upcoming = [m for m in months if m >= rules.today().strftime("%Y-%m")]
        month = upcoming[0] if upcoming else (months[-1] if months else None)
    sch = db.scalar(select(Schedule).where(Schedule.month == month, Schedule.published)) if month else None
    ctx = {"months": months, "month": month, "sch": sch, "cur": cur, "partner": partner, "a": a, "b": b}
    if not sch:
        return ctx
    rep = sch.report
    ctx["people"] = sorted(rep["people"], key=lambda x: x["name"])
    q = select(Swap).where(Swap.schedule_id == sch.id).order_by(Swap.id.desc())
    if p.is_admin:
        ctx["swaps"] = db.scalars(q).all()
        ctx["a_shifts"] = my_shift_options(rep, a, future_only=False) if a else []
        ctx["b_shifts"] = my_shift_options(rep, b, future_only=False) if b else []
        return ctx
    me = p.user.id
    ctx["me_in"] = swaps.person(rep, me) is not None
    ctx["my_shifts"] = my_shift_options(rep, me)
    ctx["partner_shifts"] = my_shift_options(rep, partner) if partner else []
    mine = db.scalars(q.where((Swap.requester_id == me) | (Swap.partner_id == me))).all()
    ctx["swaps"] = mine
    # czy oczekująca zamiana nadal jest wykonalna (podgląd dla osoby akceptującej)
    check = {}
    for sw in mine:
        if sw.status == "pending":
            try:
                _, warn = swaps.apply_swap(rep, sw.requester_id, (sw.give_day, sw.give_shift), sw.partner_id,
                                           (sw.take_day, sw.take_shift) if sw.take_day else None)
                check[sw.id] = {"ok": True, "warnings": [w for w in warn if w.startswith(p.user.full_name)]}
            except swaps.SwapError as e:
                check[sw.id] = {"ok": False, "error": str(e)}
    ctx["check"] = check
    return ctx


def commit_report(db: Session, sch: Schedule, new_rep: dict, uids):
    """Zapisuje zmieniony grafik (JSON + Excel). Jeśli saldo było już zatwierdzone, koryguje je o różnicę punktów
    uciążliwości osób, których zmiana dotyczy (osoba dodana spoza grafiku liczy się od zera)."""
    old_rep = sch.report
    if sch.saldo_applied:
        for uid in uids:
            u = db.get(User, uid)
            before, after = swaps.person(old_rep, uid), swaps.person(new_rep, uid)
            if u and after:
                u.saldo = u.saldo + (after["b"] - (before["b"] if before else 0))
    sch.report = new_rep  # nowy obiekt (a nie mutacja w miejscu), żeby SQLAlchemy wykrył zmianę JSON
    sch.xlsx = write_schedule(new_rep)


def commit_swap(db: Session, sch: Schedule, sw: Swap, new_rep: dict):
    commit_report(db, sch, new_rep, (sw.requester_id, sw.partner_id))
    sw.status = "applied"
    sw.decided_at = dt.datetime.utcnow()


@app.get("/zamiany", response_class=HTMLResponse)
def swaps_page(request: Request, month: str | None = None, partner: int | None = None, a: int | None = None,
               b: int | None = None, msg: str | None = None, db: Session = Depends(get_db),
               p: Principal = Depends(login_required)):
    return render(request, "zamiany.html", msg=msg, **swap_context(db, p, month, partner, a, b))


@app.post("/zamiany/new", response_class=HTMLResponse)
def swap_new(request: Request, schedule_id: int = Form(...), give: str = Form(...), partner_id: int = Form(...),
             take: str = Form(""), db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    if p.is_admin:
        raise HTTPException(403, "Administrator wprowadza zamiany formularzem administratora")
    sch = db.get(Schedule, schedule_id)
    if not sch or not sch.published:
        raise HTTPException(404, "Zamiany są możliwe tylko w opublikowanym grafiku")
    g, t = parse_shift(give), parse_shift(take)
    me = p.user.id
    try:
        for d, s in [x for x in (g, t) if x]:
            if swaps.shift_date(sch.month, d) < rules.today():
                raise swaps.SwapError("Nie można zamieniać zmian z przeszłości.")
        swaps.apply_swap(sch.report, me, g, partner_id, t)  # próba na sucho: czy w ogóle da się zamienić
        dup = db.scalar(select(Swap.id).where(Swap.schedule_id == sch.id, Swap.status == "pending",
                                              Swap.requester_id == me, Swap.give_day == g[0], Swap.give_shift == g[1]))
        if dup:
            raise swaps.SwapError("Masz już oczekującą prośbę o zamianę tej zmiany.")
    except swaps.SwapError as e:
        return render(request, "zamiany.html", error=str(e), **swap_context(db, p, sch.month, partner_id, None, None))
    db.add(Swap(schedule_id=sch.id, requester_id=me, partner_id=partner_id, give_day=g[0], give_shift=g[1],
                take_day=t[0] if t else None, take_shift=t[1] if t else None))
    db.commit()
    return send(f"/zamiany?month={sch.month}", "Prośba wysłana. Zamiana nastąpi po akceptacji drugiej osoby.")


def _load_swap(db, swap_id) -> tuple[Swap, Schedule]:
    sw = db.get(Swap, swap_id)
    if not sw:
        raise HTTPException(404, "Nie ma takiej zamiany")
    # blokada wiersza grafiku (Postgres: SELECT … FOR UPDATE): dwie równoległe akceptacje nie nadpiszą sobie zmian
    sch = db.scalar(select(Schedule).where(Schedule.id == sw.schedule_id).with_for_update()
                    .execution_options(populate_existing=True))
    db.refresh(sw)
    return sw, sch


@app.post("/zamiany/{swap_id}/accept")
def swap_accept(swap_id: int, db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    sw, sch = _load_swap(db, swap_id)
    if p.is_admin or sw.partner_id != p.user.id:
        raise HTTPException(403, "Tylko osoba, do której skierowano prośbę, może ją zaakceptować")
    if sw.status != "pending":
        return send(f"/zamiany?month={sch.month}", "Ta prośba nie jest już aktywna.")
    try:
        for d, s in [(sw.give_day, sw.give_shift)] + ([(sw.take_day, sw.take_shift)] if sw.take_day else []):
            if swaps.shift_date(sch.month, d) < rules.today():
                raise swaps.SwapError("Nie można zamieniać zmian z przeszłości.")
        if not sch.published:
            raise swaps.SwapError("Grafik nie jest już opublikowany.")
        new_rep, _ = swaps.apply_swap(sch.report, sw.requester_id, (sw.give_day, sw.give_shift), sw.partner_id,
                                      (sw.take_day, sw.take_shift) if sw.take_day else None)
    except swaps.SwapError as e:
        sw.status, sw.note, sw.decided_at = "failed", str(e)[:500], dt.datetime.utcnow()
        db.commit()
        return send(f"/zamiany?month={sch.month}", f"Zamiana nie jest już możliwa: {e}")
    sw.note = ""
    commit_swap(db, sch, sw, new_rep)
    db.commit()
    return send(f"/zamiany?month={sch.month}", "Zamiana zaakceptowana i wprowadzona do grafiku.")


@app.post("/zamiany/{swap_id}/reject")
def swap_reject(swap_id: int, db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    sw, sch = _load_swap(db, swap_id)
    if p.is_admin or sw.partner_id != p.user.id:
        raise HTTPException(403, "Tylko osoba, do której skierowano prośbę, może ją odrzucić")
    if sw.status == "pending":
        sw.status, sw.decided_at = "rejected", dt.datetime.utcnow()
        db.commit()
    return send(f"/zamiany?month={sch.month}", "Prośba odrzucona.")


@app.post("/zamiany/{swap_id}/cancel")
def swap_cancel(swap_id: int, db: Session = Depends(get_db), p: Principal = Depends(login_required)):
    sw, sch = _load_swap(db, swap_id)
    if not p.is_admin and sw.requester_id != p.user.id:
        raise HTTPException(403, "Tylko autor prośby może ją anulować")
    if sw.status == "pending":
        sw.status, sw.decided_at = "cancelled", dt.datetime.utcnow()
        db.commit()
    return send(f"/zamiany?month={sch.month}", "Prośba anulowana.")


@app.post("/zamiany/admin", response_class=HTMLResponse)
def swap_admin(request: Request, schedule_id: int = Form(...), a_uid: int = Form(...), give: str = Form(...),
               b_uid: int = Form(...), take: str = Form(""), db: Session = Depends(get_db),
               p: Principal = Depends(admin_required)):
    """Administrator wprowadza zamianę bez akceptacji; twarde warunki (kierowca i kierownik) nadal obowiązują."""
    sch = db.scalar(select(Schedule).where(Schedule.id == schedule_id).with_for_update()
                    .execution_options(populate_existing=True))
    if not sch or not sch.published:
        raise HTTPException(404, "Zamiany wprowadza się w opublikowanym grafiku")
    g, t = parse_shift(give), parse_shift(take)
    try:
        new_rep, warn = swaps.apply_swap(sch.report, a_uid, g, b_uid, t)
    except swaps.SwapError as e:
        return render(request, "zamiany.html", error=str(e), **swap_context(db, p, sch.month, None, a_uid, b_uid))
    sw = Swap(schedule_id=sch.id, requester_id=a_uid, partner_id=b_uid, give_day=g[0], give_shift=g[1],
              take_day=t[0] if t else None, take_shift=t[1] if t else None, by_admin=True,
              note="; ".join(warn)[:500])
    db.add(sw)
    commit_swap(db, sch, sw, new_rep)
    db.commit()
    return send(f"/zamiany?month={sch.month}", "Zamiana wprowadzona." + (f" Uwaga: {'; '.join(warn)}." if warn else ""))


# --------------------------------------------------------------------------
# Ręczna edycja grafiku (administrator): dodaj / zdejmij osobę ze zmiany
# --------------------------------------------------------------------------
def extra_person(db: Session, u: User, month: str) -> dict:
    """Wpis w raporcie dla osoby spoza grafiku (np. bez dyspozycji), z jej limitami z bazy."""
    sub = db.scalar(select(Submission).where(Submission.user_id == u.id, Submission.month == month))
    mn = sub.min_h if sub and sub.min_h is not None else u.min_h
    mx = sub.max_h if sub and sub.max_h is not None else u.max_h
    try:
        mn, mx, note = law.apply_limit(month, u.only_job, sub.other_hours if sub else None, mx, mn)
    except ValueError:
        note = "brak deklaracji godzin w innych miejscach: limit ustawowy niesprawdzony"
    return {"uid": u.id, "name": u.full_name, "role": "Kd/Kr" if u.can_drive and u.can_lead else ("Kd" if u.can_drive else "Kr"),
            "min_h": mn, "max_h": mx, "hours": 0, "n": 0, "doby": 0, "nights": 0, "offs": 0, "b": 0, "b2b": 0,
            "saldo_old": u.saldo, "saldo_new": u.saldo, "expected": 0.0, "notes": [], "law_limited": bool(note),
            "law_note": note, "below_min": False, "above_max": False, "assign": {}}


def edit_cells(db: Session, rep: dict):
    """Dla każdej zmiany: kto na niej jest i kogo można dodać (aktywni użytkownicy, którzy jeszcze na niej nie są)."""
    users = db.scalars(select(User).where(User.active).order_by(User.last_name, User.first_name)).all()
    in_rep = {p["uid"] for p in rep["people"]}
    cells = []
    for x in rep["days"]:
        row = {"day": x}
        for s in "DN":
            holders = [p for p in rep["people"] if s in p["assign"].get(str(x["d"]), "")]
            hid = {p["uid"] for p in holders}
            row[s] = {"holders": holders, "problems": rep["slots"][x["d"] - 1][s]["problems"],
                      "options": [(u.id, f"{u.full_name} {roles.icon(roles.user_code(u))}" + ("" if u.id in in_rep else " (spoza grafiku)")) for u in users if u.id not in hid]}
        cells.append(row)
    return cells


@app.get("/schedules/{sid}/edycja", response_class=HTMLResponse)
def schedule_edit_page(request: Request, sid: int, msg: str | None = None, db: Session = Depends(get_db),
                       p: Principal = Depends(admin_required)):
    sch = db.get(Schedule, sid)
    if not sch:
        raise HTTPException(404, "Nie ma takiego grafiku")
    edits = db.scalars(select(ScheduleEdit).where(ScheduleEdit.schedule_id == sid).order_by(ScheduleEdit.id.desc())).all()
    return render(request, "edycja.html", sch=sch, rep=sch.report, cells=edit_cells(db, sch.report), edits=edits, msg=msg)


@app.post("/schedules/{sid}/edit", response_class=HTMLResponse)
def schedule_edit(request: Request, sid: int, uid: int = Form(...), day: int = Form(...), shift: str = Form(...),
                  action: str = Form(...), db: Session = Depends(get_db), p: Principal = Depends(admin_required)):
    """Dodaje osobę do zmiany albo ją zdejmuje. Działa na grafiku roboczym i opublikowanym; każda zmiana trafia do dziennika."""
    if action not in ("add", "remove"):
        raise HTTPException(400, "Niepoprawna akcja")
    sch = db.scalar(select(Schedule).where(Schedule.id == sid).with_for_update().execution_options(populate_existing=True))
    if not sch:
        raise HTTPException(404, "Nie ma takiego grafiku")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Nie ma takiego użytkownika")
    month = sch.month
    try:
        new_rep, warnings = swaps.edit_assignment(sch.report, uid, day, shift, action == "add",
                                                  extra_person=extra_person(db, u, month))
    except swaps.SwapError as e:
        edits = db.scalars(select(ScheduleEdit).where(ScheduleEdit.schedule_id == sid).order_by(ScheduleEdit.id.desc())).all()
        return render(request, "edycja.html", sch=sch, rep=sch.report, cells=edit_cells(db, sch.report), edits=edits, error=str(e))
    if action == "add":  # ostrzeżenie o dostępności: tylko informacja, administrator może przydzielić wbrew deklaracji
        sub = db.scalar(select(Submission).where(Submission.user_id == uid, Submission.month == month))
        if sub is None:
            warnings.append(f"{u.full_name}: brak złożonej dyspozycji na {month}")
        elif shift not in sub.avail.get(str(day), ""):
            warnings.append(f"{u.full_name}: nie zadeklarował(a) dostępności na tę zmianę")
    commit_report(db, sch, new_rep, (uid,))
    db.add(ScheduleEdit(schedule_id=sid, user_id=uid, day=day, shift=shift, action=action, note="; ".join(warnings)[:1000]))
    db.commit()
    verb = "Dodano" if action == "add" else "Zdjęto"
    return send(f"/schedules/{sid}/edycja", f"{verb}: {u.full_name}, {swaps.label(month, day, shift)}."
                + (f" Uwaga: {'; '.join(warnings)}." if warnings else ""))
