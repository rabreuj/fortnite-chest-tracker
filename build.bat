@echo off
setlocal
title Compilar Fortnite Chest Tracker v1.1
cd /d "%~dp0"

set APP_NAME=FortniteChestTracker
set VERSION=1.1
set ENTRY=fortnite_tracker.pyw
set REL=%APP_NAME%-v%VERSION%-win64

echo.
echo === Compilando %APP_NAME% v%VERSION% ===
echo.

if not exist "%ENTRY%"                 ( echo [ERROR] Falta %ENTRY% & pause & exit /b 1 )
if not exist "icono_app.ico"           ( echo [ERROR] Falta icono_app.ico & pause & exit /b 1 )
if not exist "pirate-shop-token.png"   ( echo [ERROR] Falta pirate-shop-token.png & pause & exit /b 1 )

echo [1/5] Limpiando builds anteriores (incluido el .spec viejo)...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo [2/5] Comprobando PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo     No instalado. Instalando...
    python -m pip install "pyinstaller>=6.0"
    if errorlevel 1 ( echo [ERROR] No se pudo instalar PyInstaller. & pause & exit /b 1 )
)

echo [3/5] Compilando...
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name "%APP_NAME%" ^
    --icon="icono_app.ico" ^
    --add-data "icono_app.ico;." ^
    --add-data "pirate-shop-token.png;." ^
    --collect-all customtkinter ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    "%ENTRY%"
if errorlevel 1 ( echo. & echo [ERROR] Fallo la compilacion. & pause & exit /b 1 )

echo [4/5] Empaquetando release...
if exist release rmdir /s /q release
mkdir "release\%REL%"
copy "dist\%APP_NAME%.exe" "release\%REL%\" >nul
copy "icono_app.ico"       "release\%REL%\icono_app.ico" >nul
copy "README.md"           "release\%REL%\README.md" >nul
if exist LICENSE copy "LICENSE" "release\%REL%\LICENSE.txt" >nul

powershell -NoProfile -Command "Compress-Archive -Path 'release\%REL%\*' -DestinationPath 'release\%REL%.zip' -Force"
powershell -NoProfile -Command "(Get-FileHash 'release\%REL%.zip' -Algorithm SHA256).Hash.ToLower() + '  %REL%.zip' | Out-File -Encoding ascii 'release\%REL%.zip.sha256'"

echo [5/5] Listo.
echo.
echo   dist\%APP_NAME%.exe
echo   release\%REL%.zip
echo   release\%REL%.zip.sha256
echo.
echo IMPORTANTE: abre el .exe y comprueba que el titulo diga v%VERSION%.
echo.
pause