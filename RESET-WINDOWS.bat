@echo off
setlocal
cd /d "%~dp0"
title Grafik - kasowanie danych testowych
echo UWAGA: to usunie WSZYSTKIE dane testowe (uzytkownikow, dyspozycje, grafiki).
set /p ODP=Aby kontynuowac wpisz TAK i nacisnij Enter: 
if /i not "%ODP%"=="TAK" goto CANCEL
docker compose down -v
if exist .dane-demo-wczytane del .dane-demo-wczytane
echo.
echo Gotowe. Przy nastepnym uruchomieniu START-WINDOWS.bat dane demo wczytaja sie od nowa.
pause
exit /b 0
:CANCEL
echo Anulowano. Nic nie zostalo usuniete.
pause
exit /b 0
