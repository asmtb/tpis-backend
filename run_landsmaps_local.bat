@echo off
:: run_landsmaps_local.bat
:: Run LandsMaps Collector locally instead of Cloud Run
:: (Incapsula binds cookies to the originating IP — Google Cloud IPs are always blocked)
::
:: Usage:
::   run_landsmaps_local.bat              — normal run (new assets only)
::   run_landsmaps_local.bat --retry      — retry all not_found from previous runs
::                                          (ignores checkpoint + ignores 30-day cooldown)

setlocal
cd /d "%~dp0"

set RETRY_FLAG=
if /i "%1"=="--retry" set RETRY_FLAG=--retry-not-found

echo.
echo ===================================================
echo   TPIS LandsMaps Collector - Local Mode
if defined RETRY_FLAG (
echo   Mode: RETRY not_found ^(ignore checkpoint^)
) else (
echo   Mode: Normal ^(new assets only^)
)
echo   %DATE% %TIME%
echo ===================================================
echo.
echo [1/2] Checking environment...

if not exist ".env" (
    echo [ERROR] .env file not found.
    echo         Please create .env with SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    echo         RESEND_API_KEY, NOTIFY_EMAIL before running.
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python first.
    pause
    exit /b 1
)

echo [OK] .env and Python found.
echo.
echo [2/2] Starting LandsMaps Collector...
echo       Chromium will open - solve hCaptcha then click Submit.
echo.

python landsmaps_collector_local.py %RETRY_FLAG%

echo.
if errorlevel 1 (
    echo [FAILED] Collector failed - see log above.
) else (
    echo [DONE] Collector finished - check your inbox for the summary email.
)

echo.
pause
