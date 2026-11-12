@echo off
setlocal
title Dependencias - Fortnite Chest Tracker v1.1
cd /d "%~dp0"

echo.
echo === Fortnite Chest Tracker v1.1 - dependencias ===
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta en el PATH.
    echo Instala Python 3.9 o superior desde https://www.python.org/downloads/
    echo y marca "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
)

python --version
echo.
echo Actualizando pip...
python -m pip install --upgrade pip

echo.
echo Instalando dependencias de la aplicacion...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo.
set /p BUILD="Instalar tambien PyInstaller para compilar el .exe? (S/N): "
if /i "%BUILD%"=="S" python -m pip install "pyinstaller>=6.0"

echo.
echo === Listo ===
echo Ejecutar la app:   doble click en fortnite_tracker.pyw
echo Con consola:       python fortnite_tracker.pyw --debug
echo Compilar el .exe:  build.bat
echo Probar la logica:  python test_logic.py
echo.
pause