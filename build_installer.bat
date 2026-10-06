@echo off
chcp 65001 >nul
echo ====================================================
echo  Сборка инсталлятора Universal Media Downloader v3.1
echo ====================================================
echo.

if exist "D:\Inno Setup 6\ISCC.exe" (
    set "ISCC_EXE=D:\Inno Setup 6\ISCC.exe"
) else (
    where iscc >nul 2>&1
    if %errorlevel% equ 0 (
        set "ISCC_EXE=iscc"
    ) else (
        echo [ОШИБКА] Inno Setup компилятор (ISCC.exe) не найден!
        pause
        exit /b 1
    )
)

echo Запуск Inno Setup...
"%ISCC_EXE%" "%~dp0installer.iss"
if %errorlevel% equ 0 (
    echo.
    echo [УСПЕХ] Инсталлятор собран в папке output\
) else (
    echo.
    echo [ОШИБКА] Сборка завершилась с ошибкой.
)

pause
