@echo off
setlocal
cd /d "%~dp0"
title Grafik - uruchamianie
echo.
echo ==================================================
echo   Grafik: uruchamianie na tym komputerze
echo ==================================================
echo.

where docker >nul 2>nul
if errorlevel 1 goto NO_DOCKER
docker info >nul 2>nul
if errorlevel 1 goto DOCKER_OFF

if not exist .env (
  copy /y ustawienia-lokalne.env .env >nul
  echo Utworzono plik .env z gotowymi ustawieniami.
)

echo Budowanie i uruchamianie aplikacji. Za pierwszym razem trwa to kilka minut, prosze czekac...
echo.
docker compose up -d --build
if errorlevel 1 goto FAILED

echo.
echo Czekam, az aplikacja bedzie gotowa...
powershell -NoProfile -Command "for ($i=0; $i -lt 90; $i++) { try { Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8000/login -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 2 } }; exit 1"
if errorlevel 1 goto NOT_READY

if exist .dane-demo-wczytane goto DEMO_DONE
echo Wczytuje dane testowe: 12 osob demo...
docker compose exec -T web python -m app.demo --month auto --users 12
if errorlevel 1 goto FAILED
echo wczytano> .dane-demo-wczytane
:DEMO_DONE

echo.
echo ==================== GOTOWE ====================
echo   Adres:           http://localhost:8000
echo.
echo   Administrator:   login  admin
echo                    haslo  Admin-Lokalnie-123
echo.
echo   Uzytkownik:      login  jan.kowalski
echo                    haslo  demo12345
echo   Inni uzytkownicy demo: login imie.nazwisko, to samo haslo demo12345
echo ================================================
echo.
echo Otwieram przegladarke. Aby zakonczyc, uruchom STOP-WINDOWS.bat.
start "" http://localhost:8000
pause
exit /b 0

:NO_DOCKER
echo NIE ZNALEZIONO DOCKERA.
echo Zainstaluj Docker Desktop: https://www.docker.com/products/docker-desktop/
echo Po instalacji uruchom Docker Desktop, poczekaj az sie wlaczy i uruchom ten plik ponownie.
echo.
pause
exit /b 1

:DOCKER_OFF
echo DOCKER NIE JEST URUCHOMIONY.
echo Otworz aplikacje Docker Desktop z menu Start i poczekaj, az ikona wieloryba przestanie sie animowac.
echo Potem uruchom ten plik ponownie.
echo.
pause
exit /b 1

:NOT_READY
echo Aplikacja nie odpowiada. Ostatnie komunikaty:
docker compose logs --tail 30 web
echo.
echo Zrob zrzut ekranu tego okna i wyslij go dalej.
pause
exit /b 1

:FAILED
echo.
echo Cos poszlo nie tak. Zrob zrzut ekranu tego okna i wyslij go dalej.
pause
exit /b 1
