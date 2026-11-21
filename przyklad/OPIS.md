# Przykład: 12 osób, styczeń 2027

Dane są losowe (demo). Kierownikiem jest każdy, kierowcami wszyscy poza Marią Nowak i Pawłem Grabowskim.
Lista osób, ich ról i limitów godzin: `osoby_demo.csv`.

| Co | Gdzie |
|---|---|
| Gotowy grafik, pełny (grafik, obsada, podsumowanie, diagnostyka), dla admina | `grafik_2027-01_admin.xlsx` |
| Gotowy grafik dla użytkowników (bez danych prywatnych kolegów) | `grafik_2027-01_dla_uzytkownikow.xlsx` |

## Jak wypróbować w aplikacji
1. Wczytaj osoby i ich dyspozycje gotowcem: `python -m app.demo --month 2027-01 --users 12` (hasło wszystkich: `demo12345`).
   Albo dodaj osoby z `osoby_demo.csv` w zakładce **Użytkownicy**.
2. Zaloguj się jako wybrany użytkownik (np. `jan.kowalski`), wejdź w **Dyspozycje**, zaznacz w kalendarzu D / N / DN i zapisz.
   Jako admin możesz wypełnić dyspozycję dowolnej osoby (lista „Osoba" nad kalendarzem).
3. **Generuj grafik** → obejrzyj → **Opublikuj**, żeby użytkownicy go zobaczyli.

Termin: dyspozycje na styczeń można składać do 10 grudnia 2026, od 11 grudnia jest blokada (admin może zmieniać zawsze).

## Wynik tego przykładu
0 braków w obsadzie, nikt poniżej minimum, godziny między 120 a 132 na osobę, 3–5 dób na osobę.
Przy każdym „Generuj” remisy są losowane, więc kolejny grafik z tych samych dyspozycji będzie nieco inny.
