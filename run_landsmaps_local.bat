@echo off
:: run_landsmaps_local.bat
:: Run LandsMaps Collector locally instead of Cloud Run
:: (Incapsula binds cookies to the originating IP — Google Cloud IPs are always blocked)
::
:: Usage:
::   double-click this file
::   or: cd E:\Website\TPIS\tpis_production && run_landsmaps_local.bat
::
:: What happens:
::   1. Chromium opens automatically
::   2. Solve hCaptcha (if prompted) then click Submit
::   3. Browser closes itself -> collector starts immediately
::   4. Results written to Supabase (parcels, asset_parcels)
::   5. Summary email sent to your inbox

setlocal

:: ---- Always cd to project root regardless of where this file is launched from ----
cd /d "%~dp0"

echo.
echo ===================================================
echo   TPIS LandsMaps Collector - Local Mode
echo   %DATE% %TIME%
echo ===================================================
echo.
echo [1/2] Checking environment...

:: Check .env exists
if not exist ".env" (
    echo [ERROR] .env file not found.
    echo         Please create .env with SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    echo         RESEND_API_KEY, NOTIFY_EMAIL before running.
    pause
    exit /b 1
)

:: Check Python exists
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

python landsmaps_collector_local.py

echo.
if errorlevel 1 (
    echo [FAILED] Collector failed - see log above.
) else (
    echo [DONE] Collector finished - check your inbox for the summary email.
)

echo.
pause
