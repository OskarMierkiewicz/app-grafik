# Grafik - Lux Med Wileńska 44 (web + baza w kontenerach)

1 karetka, zmiany D (7-19) i N (19-7), 2 osoby na zmianie, w tym min. 1 kierowca i min. 1 kierownik.
Dwa kontenery: **web** (FastAPI + solver OR-Tools CP-SAT) i **db** (Postgres).

## Uruchomienie
```
cp .env.example .env        # ustaw POSTGRES_PASSWORD, ADMIN_PASSWORD i SECRET_KEY
docker compose up -d --build
```
Aplikacja: http://localhost:8000 (port bazy nie jest wystawiony na zewnątrz). Dane Postgresa są w wolumenie `dbdata`.

Dane demo: `docker compose exec web python -m app.demo --month 2027-01 --users 12`
(użytkownicy demo: login `imię.nazwisko`, np. `jan.kowalski`, hasło `demo12345`).
Gotowy przykład na 12 osobach (pliki dyspozycji i wygenerowany grafik w Excelu) jest w folderze `przyklad/`, opis w `przyklad/OPIS.md`.
Nowy zestaw: `python -m app.demo --month 2027-01 --users 12 --export przyklad` (na pustej/osobnej bazie).
Po wcześniejszym uruchomieniu z większą liczbą osób: `python -m app.demo --month 2026-12 --users 12 --trim` usuwa nadmiarowe osoby demo
(z kontami i dyspozycjami; rozpoznaje je po imieniu i nazwisku, więc prawdziwa osoba o takich danych też zostałaby usunięta).

## Test na dropletcie bez domeny (tylko HTTP)
Bez domeny nie ma HTTPS, więc hasła idą otwartym tekstem: używaj tylko danych demo (`python -m app.demo`) i **nie ustawiaj `SESSION_HTTPS_ONLY=1`**
(przy HTTP logowanie przestałoby działać). Dwa bezpieczniejsze warianty:
- **tunel SSH (zero ekspozycji):** w `.env` `WEB_BIND=127.0.0.1`, a u siebie `ssh -L 8000:localhost:8000 root@IP_DROPLETA` i wejście na http://localhost:8000;
- **publiczny adres IP:** `http://IP_DROPLETA:8000`, ale port 8000 ogranicz w **DigitalOcean Cloud Firewall** do adresów IP ekipy.
Uwaga: Docker omija regułę UFW na serwerze dla opublikowanych portów, więc samo `ufw` nie wystarczy: użyj Cloud Firewall albo `WEB_BIND=127.0.0.1`.

## Wybór miesiąca
Zamiast wpisywać miesiąc, klikasz przycisk z nazwą (np. „styczeń 2027 ▾"): otwiera się siatka 12 miesięcy ze strzałkami zmiany roku
i skrótami „Ten miesiąc" / „Następny"; miesiące, w których są dyspozycje lub grafiki, mają kropkę. Wybór od razu odświeża stronę.
Wybieracz jest własny (`app/static/monthpicker.js`, bez zewnętrznych bibliotek), bo natywne pole miesiąca nie działa w każdej przeglądarce.

## Logowanie i role
- **Administrator**: login `ADMIN_LOGIN` (domyślnie `admin`), hasło `ADMIN_PASSWORD` z `.env`. Widzi wszystko, zarządza
  użytkownikami, wgrywa pliki za wszystkich, generuje i publikuje grafiki, wprowadza zamiany. Bez `ADMIN_PASSWORD` aplikacja
  wypisze w logu losowe hasło tymczasowe (`docker compose logs web`).
- **Użytkownik** (każda osoba z tabeli `users`, która ma konto z hasłem w `user_accounts`): login z tabeli kont (domyślnie
  `imię.nazwisko` małymi literami bez polskich znaków), hasło ustawia administrator (użytkownik zmienia je i swój e-mail w „Moje konto"). Użytkownik widzi opublikowane grafiki (bieżący i poprzednie),
  listę, kto złożył dyspozycję, wgrywa własny plik i prosi o zamiany. Osoba bez hasła nie może się zalogować.
- `SECRET_KEY` podpisuje sesje (długi losowy ciąg); bez niego wszyscy są wylogowani po restarcie. Za HTTPS ustaw `SESSION_HTTPS_ONLY=1`.
  Po 5 nieudanych próbach logowania jest 5-minutowa blokada.

## Dyspozycje i termin
Użytkownik pobiera **własny szablon** (z imieniem i nazwiskiem; plik nazywa się `RRRR-MM.xlsx`), wypełnia i wgrywa plik o nazwie
`RRRR-MM.xlsx` (np. `2027-01.xlsx`): z nazwy wiadomo, którego miesiąca dotyczy (musi zgadzać się z miesiącem w środku pliku i z imieniem
zalogowanej osoby). Dyspozycję na miesiąc M można składać i podmieniać **do 10. dnia miesiąca poprzedzającego M** (włącznie, zmienna
`SUBMISSION_DEADLINE_DAY`); od 11. jest blokada. Blokada działa też wcześniej, **gdy administrator wygenerował już grafik na M**
(żeby ponownie otworzyć zapisy, usuń roboczy grafik). Administrator nie podlega blokadzie.

## Publikacja i zamiany
Grafik wygenerowany przez admina jest **roboczy**, widzi go tylko admin. **Opublikuj** udostępnia go użytkownikom (jeden opublikowany na miesiąc).
W opublikowanym grafiku użytkownicy mogą prosić o **zamianę** zmian (zakładka Zamiany): wybierają swoją zmianę, kolegę i (opcjonalnie)
jego zmianę w zamian. Autor akceptuje przez złożenie prośby, druga osoba musi **zaakceptować**; wtedy zamiana wchodzi do grafiku
(Excel generuje się ponownie, a zatwierdzone saldo jest korygowane). Twarde warunki sprawdzane przy składaniu i akceptacji: na zmianie
nadal kierowca i kierownik, max 2 osoby, nikt nie przekracza max godzin, bez zmian z przeszłości. Administrator może wprowadzić zamianę
sam (bez akceptacji, te same twarde warunki).

## Ręczna edycja grafiku (administrator)
Na stronie grafiku przycisk **Edytuj ręcznie** otwiera tabelę dzień × zmiana (D/N): przy każdej osobie jest **×** (zdejmij ze zmiany),
a pod nią lista z **+** (dodaj osobę, także spoza grafiku, np. bez dyspozycji). Działa na grafiku roboczym i opublikowanym
(po publikacji użytkownicy od razu widzą zmianę, a Excel generuje się ponownie).
- **Twarde zasady:** najwyżej 2 osoby na zmianie, a przy dwóch musi być kierowca i kierownik. Złamanie jest blokowane.
- **Ostrzeżenia** (nie blokują): zdjęcie osoby zostawia zmianę z brakiem (czerwona), przekroczone maksimum godzin,
  brak deklarowanej dostępności lub dyspozycji, N→D bez przerwy, spadek poniżej minimum.
- **Dziennik:** każda zmiana (kto, kiedy, co, ostrzeżenia) zapisuje się i jest widoczna dla admina na stronie grafiku i edycji.
- Jeśli saldo było już zatwierdzone, jest korygowane o różnicę punktów uciążliwości. Oczekujące zamiany, których edycja
  admina nie pozwala już wykonać, kończą się statusem „niewykonalna".
- Dla pojedynczej wymiany osób (A oddaje, B przejmuje) jest też prostszy formularz w zakładce **Zamiany**.

## Użytkownicy (tabela `users`)
imię, nazwisko, `can_drive` (kierowca, domyślnie false), `can_lead` (kierownik, domyślnie true),
`min_h`, `max_h` (domyślne limity godzin), `saldo`, `active`, `only_job`. Zarządzane w zakładce **Użytkownicy**.

## Import użytkowników z pliku CSV
```
docker compose exec -T web python -m app.import_users - --dry-run < przyklad/osoby.csv   # podgląd, nic nie zapisuje
docker compose exec -T web python -m app.import_users - < przyklad/osoby.csv             # zapis
```
(`-` = plik ze standardowego wejścia, `-T` jest potrzebne przy `<`; bez Dockera: `python -m app.import_users osoby.csv`.)
Kolumny rozpoznawane po nagłówkach: `login`, `osoba` (Imię Nazwisko; albo osobno `imię` i `nazwisko`), `rola` (`kierownik`,
`kierowca + kierownik`, `tylko kierowca`), `godziny min-max` (np. `96-144`), `jedyne miejsce pracy` (`tak`/`nie`), opcjonalnie
`e-mail` i `hasło`. Nowe osoby bez hasła w pliku dostają **losowe hasło, wypisane raz na końcu** (w bazie jest tylko hash).
Istniejące osoby (to samo imię i nazwisko) są aktualizowane, ich hasło zmienia się tylko, gdy podasz je w pliku; nic nie jest usuwane.
Plik jest w całości sprawdzany przed zapisem: przy jakimkolwiek błędzie nie zapisuje się nic.
**`--sync`**: baza ma zawierać *tylko* osoby z pliku, czyli osoby spoza pliku (np. stare osoby demo) są **usuwane** razem z kontami,
dyspozycjami i zamianami. Najpierw uruchom z `--dry-run`, żeby zobaczyć listę. Pusty plik z `--sync` jest odrzucany (nie skasuje wszystkich).
Wygenerowane wcześniej grafiki zostają w bazie (zawierają imiona usuniętych osób): usuń je w panelu admina.

## Hasła użytkowników
Hasła **nie da się odczytać**: w bazie jest tylko hash, a losowe hasła z importu wypisują się raz na końcu jego wyniku (zapisz je od razu,
np. `... > hasla.txt`). Nowe hasła ustawisz:
- jednej osobie: panel admina → Użytkownicy → pole „Nowe hasło” → Zapisz,
- hurtowo: `docker compose exec -T web python -m app.reset_passwords --all > hasla.csv` (albo `--login jan.kowalski ewa.samul`,
  albo `--all --same-password 'Start2027!'`). Na stdout trafia czysty CSV `login;osoba;hasło`, a stare sesje tych osób wygasają.
Hasło admina to `ADMIN_PASSWORD` z `.env` (nie ma go w bazie).

## Konta (tabela `user_accounts`, osobna, powiązana z `users` przez `user_id`)
`login` (unikalny, małe litery), `password_hash` (pbkdf2, NULL = nie można się zalogować), `email` (do kontaktu), `user_id`.
Login domyślnie powstaje z imienia i nazwiska (`lukasz.zak`), ale admin może go zmienić. Wiersz można też dodać zwykłym SQL-em
(`INSERT INTO user_accounts (user_id, login, email) VALUES (...)`), a hasło ustawić potem w zakładce Użytkownicy
(hasła są tylko w postaci hasha, więc nie wpisuje się ich w SQL-u). Usunięcie użytkownika usuwa jego konto. Starsze bazy z hasłami
w `users.password_hash` są przy starcie automatycznie przenoszone do `user_accounts`.

## Przepływ pracy
1. **Grafik → Pobierz pusty formularz** na miesiąc i roześlij.
2. Osoba wpisuje imię, nazwisko, opcjonalnie min/max godzin i dla każdego dnia D / N / DN / puste.
   Puste min/max = domyślne z bazy. Rola pochodzi z bazy.
3. Wgrywasz pliki (wiele naraz). Każdy plik jest sprawdzany: nieznana osoba, zła wartość, min > max, zły plik.
   Ponowne wgranie pliku tej samej osoby zastępuje poprzednią dyspozycję.
4. **Generuj grafik** → podgląd (siatka, obsada dzień po dniu, braki na czerwono, podsumowanie), pobranie Excela.
5. **Zatwierdź** zapisuje saldo uciążliwości do bazy (raz na miesiąc), żeby kolejny miesiąc był sprawiedliwszy.

## Limit ustawowy dla osób pracujących w kilku miejscach (`only_job`)
Nowelizacja ustawy o świadczeniach opieki zdrowotnej (Sejm przyjął poprawki Senatu 19.11.2026, czeka na podpis
prezydenta) ma ograniczać łączny czas pracy medyka u wszystkich pracodawców do 2 etatów (wg prasy: 320 h).
W aplikacji: `users.only_job` (domyślnie true). Dla `only_job=false` osoba **musi** w formularzu podać „Godziny w innych
miejscach pracy” (0 = wcale), a jej max h w grafiku to `min(max h, 320 − godziny gdzie indziej)`. Brak deklaracji
albo godziny przy `only_job=true` = plik odrzucony. Zmienne środowiskowe (`app/law.py`):
`LAW_ENABLED` (1/0), `LAW_EFFECTIVE_FROM` (domyślnie `2027-01`), `LAW_TOTAL_MAX_H` (domyślnie `320`).
Szczegóły ustawy (czy 320 h jest miesięczne, dyżury, czy objęte są ZRM) są niepotwierdzone w tekście: zweryfikuj z prawnikiem.

## Zasady
Twarde: tylko zadeklarowana dostępność, max h, max 2 osoby na zmianie, D+N tej samej osoby = doba,
brak pary kierowca+kierowca (bez uprawnień kierownika) ani kierownik+kierownik.

Układanie idzie **etapami** (kolejność ważności, każdy etap blokuje wynik poprzedniego):
1. każdy dobija do swojego minimum godzin,
2. dopiero potem uzupełniane są braki w obsadzie (osoba / kierowca / kierownik),
3. **doby mają pierwszeństwo**: kto wpisał DN w danym dniu, dostaje całą dobę (D+N), a nie pojedynczą zmianę,
4. nadwyżki godzin dostają osoby z najmniejszą liczbą godzin, które zadeklarowały dostępność w niezapełnione dni
   (minimalizacja sumy kwadratów godzin),
5. równa uciążliwość (noce, weekendy, święta, saldo) i unikanie N→D bez przerwy,
6. remisy rozstrzyga losowanie. Każde „Generuj" daje inny wariant (seed jest w Diagnostyce).

Doby nie odbierają pierwszeństwa minimom ani uzupełnianiu braków (kroki 1–2), bo te są ważniejsze.

Jeśli kogoś nie da się obsadzić w parze (np. w danym dniu zostają dwaj kierowcy bez uprawnień kierownika), zmiana
zostaje z 1 osobą i dostaje „BRAK", zamiast niedozwolonej pary.

## Rozwój lokalny (bez Dockera)
```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload      # domyślnie SQLite ./local.db
```
