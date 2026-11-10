@echo off
chcp 65001 >nul
title Fortnite Chest Tracker - Instalador
color 0A

echo ==========================================
echo   INSTALADOR DE FORTNITE CHEST TRACKER
echo ==========================================
echo.

:: 1. Comprobar si Python está instalado
python --version >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python detectado.
    set PYTHON_CMD=python
    goto :check_libs
)

py --version >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Python detectado (via py launcher).
    set PYTHON_CMD=py
    goto :check_libs
)

:: Si no está instalado
color 0C
echo [ERROR] Python NO esta instalado en tu PC.
echo.
echo Este programa necesita Python 3.9 o superior para funcionar.
echo.
echo PASOS A SEGUIR:
echo 1. Se abrira la web oficial de Python en tu navegador.
echo 2. Descarga la ultima version.
echo 3. AL INSTALAR, MARCA LA CASILLA "Add Python.exe to PATH" (MUY IMPORTANTE).
echo 4. Vuelve a ejecutar este archivo .bat cuando termines.
echo.
pause
start https://www.python.org/downloads/
exit

:check_libs
echo.
echo Comprobando librerias necesarias...
echo.

:: Función para instalar librería si no existe
:: Usamos %PYTHON_CMD% -m pip show para evitar problemas de PATH en Windows

%PYTHON_CMD% -m pip show pynput >nul 2>&1
if %errorlevel% neq 0 (
    echo [INSTALANDO] pynput...
    %PYTHON_CMD% -m pip install pynput
) else (
    echo [OK] pynput ya instalada.
)

%PYTHON_CMD% -m pip show customtkinter >nul 2>&1
if %errorlevel% neq 0 (
    echo [INSTALANDO] customtkinter...
    %PYTHON_CMD% -m pip install customtkinter
) else (
    echo [OK] customtkinter ya instalada.
)

%PYTHON_CMD% -m pip show Pillow >nul 2>&1
if %errorlevel% neq 0 (
    echo [INSTALANDO] Pillow...
    %PYTHON_CMD% -m pip install Pillow
) else (
    echo [OK] Pillow ya instalada.
)

%PYTHON_CMD% -m pip show pystray >nul 2>&1
if %errorlevel% neq 0 (
    echo [OPCIONAL] pystray no detectado (para icono en bandeja).
    set /p install_tray="¿Quieres instalarlo? (s/n): "
    if /i "%install_tray%"=="s" (
        %PYTHON_CMD% -m pip install pystray
    )
) else (
    echo [OK] pystray ya instalada.
)

echo.
echo ==========================================
echo   TODO LISTO. YA PUEDES EJECUTAR EL PROGRAMA.
echo ==========================================
echo.
pause