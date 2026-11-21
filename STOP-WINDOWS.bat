@echo off
setlocal
cd /d "%~dp0"
title Grafik - zatrzymywanie
echo Zatrzymuje aplikacje (dane zostaja zapisane)...
docker compose down
echo.
echo Gotowe. Aby uruchomic ponownie, kliknij START-WINDOWS.bat.
pause
