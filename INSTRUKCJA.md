# Grafik: jak uruchomić na swoim komputerze (Windows)

Aplikacja do układania grafiku dyżurów. Uruchamiasz ją u siebie, tylko do testów. Zajmie to około 15 minut, z czego większość to czekanie.

## 1. Zainstaluj Docker Desktop (jednorazowo)
1. Wejdź na https://www.docker.com/products/docker-desktop/ i pobierz wersję dla Windows.
2. Zainstaluj (klikaj „Dalej" / „OK"). Jeśli program poprosi o restart komputera, zrób to.
3. Uruchom **Docker Desktop** z menu Start i poczekaj, aż ikona wieloryba w prawym dolnym rogu przestanie się animować.

> Docker Desktop jest darmowy do użytku prywatnego i w małych firmach. Jeśli robisz to na służbowym komputerze w dużej firmie, zapytaj najpierw IT.

## 2. Pobierz projekt
1. Wejdź na https://github.com/OskarMierkiewicz/app-grafik
2. Kliknij zielony przycisk **Code**, potem **Download ZIP**.
3. Rozpakuj plik (prawy przycisk myszy → **Wyodrębnij wszystko**), np. na Pulpit.

## 3. Uruchom
1. Otwórz rozpakowany folder i kliknij dwa razy plik **`START-WINDOWS.bat`**.
2. Jeśli Windows pokaże niebieskie okno „Windows chronił ten komputer": kliknij **Więcej informacji** → **Uruchom mimo to**.
3. Poczekaj. **Za pierwszym razem trwa to 5–10 minut** (aplikacja się buduje). Czarne okno nie jest zepsute, po prostu pracuje.
4. Gdy pojawi się napis **GOTOWE**, przeglądarka otworzy się sama. Jeśli nie, wejdź na http://localhost:8000

## 4. Zaloguj się
| Kto | Login | Hasło |
|---|---|---|
| Administrator | `admin` | `Admin-Lokalnie-123` |
| Zwykły użytkownik | `jan.kowalski` | `demo12345` |

Inni użytkownicy testowi mają login w stylu `imie.nazwisko` (np. `anna.szymanski`) i to samo hasło `demo12345`. Dane są wymyślone.

## Co wypróbować
- **Jako administrator:** zakładka **Panel admina** → wybierz miesiąc → **Generuj grafik** → obejrzyj wynik → **Opublikuj**.
- **Jako użytkownik** (wyloguj się i zaloguj jako `jan.kowalski`): **Dyspozycje** (kto już złożył), **Grafiki** (opublikowany grafik), **Zamiany** (prośba o zamianę zmiany z kolegą).

## Zatrzymanie i ponowne uruchomienie
- **Zakończenie pracy:** kliknij **`STOP-WINDOWS.bat`**. Dane zostają zapisane.
- **Kolejne uruchomienie:** znów **`START-WINDOWS.bat`** (teraz trwa kilka sekund).
- **Wyczyszczenie wszystkich danych testowych:** **`RESET-WINDOWS.bat`**.

## Jeśli coś nie działa
- **„Docker nie jest uruchomiony":** włącz Docker Desktop z menu Start, poczekaj, aż się uruchomi, i kliknij `START-WINDOWS.bat` jeszcze raz.
- **Błąd o zajętym porcie 8000:** zamknij inne programy, które mogą go używać, albo uruchom ponownie komputer.
- **Cokolwiek innego:** zrób zrzut ekranu czarnego okna i wyślij.

## Dobrze wiedzieć
- Aplikacja działa **tylko na Twoim komputerze**, nikt inny w sieci nie ma do niej dostępu.
- To wersja testowa z wymyślonymi danymi. **Nie wpisuj prawdziwych danych osobowych.**
- Hasła w tej instrukcji są tylko do testów lokalnych i nie nadają się do serwera.
