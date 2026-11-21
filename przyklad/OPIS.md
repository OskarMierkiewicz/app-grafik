# Przykład: 12 osób, styczeń 2027

Dane są losowe (demo). Kierownikiem jest każdy, kierowcami wszyscy poza Marią Nowak i Pawłem Grabowskim.
Lista osób, ich ról i limitów godzin: `osoby.csv`.

| Co | Gdzie |
|---|---|
| Pliki dyspozycji dla **użytkowników** (każdy w swoim folderze, nazwa `2027-01.xlsx`) | `dyspozycje_uzytkownikow/<login>/2027-01.xlsx` |
| Te same pliki do **hurtowego wgrania przez admina** (panel admina, „Wgraj”) | `dyspozycje_dla_admina/<login>.xlsx` |
| Gotowy grafik, pełny (grafik, obsada, podsumowanie, diagnostyka), dla admina | `grafik_2027-01_admin.xlsx` |
| Gotowy grafik dla użytkowników (bez danych prywatnych kolegów) | `grafik_2027-01_dla_uzytkownikow.xlsx` |

## Jak wypróbować w aplikacji
1. Dodaj w zakładce **Użytkownicy** te 12 osób (imię, nazwisko, kierowca tak/nie, kierownik, login z `osoby.csv`, hasło)
   albo wczytaj je gotowcem: `python -m app.demo --month 2027-01 --users 12` (hasło wszystkich: `demo12345`).
2. Zaloguj się jako wybrany użytkownik (np. `jan.kowalski`) i wgraj jego `dyspozycje_uzytkownikow/jan.kowalski/2027-01.xlsx`.
   Plik musi nazywać się dokładnie `2027-01.xlsx` i dotyczyć zalogowanej osoby.
3. Albo jako admin: panel admina → miesiąc 2027-01 → „Wgraj” → zaznacz wszystkie pliki z `dyspozycje_dla_admina/`.
4. **Generuj grafik** → obejrzyj → **Opublikuj**, żeby użytkownicy go zobaczyli.

Termin: dyspozycje na styczeń można składać do 10 grudnia 2026, od 11 grudnia jest blokada (admin może wgrywać zawsze).

## Wynik tego przykładu
0 braków w obsadzie, nikt poniżej minimum, godziny między 120 a 132 na osobę, 3–5 dób na osobę.
Przy każdym „Generuj” remisy są losowane, więc kolejny grafik z tych samych plików będzie nieco inny.
