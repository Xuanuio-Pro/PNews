@echo off
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"
if "%CARD_LIMIT%"=="" set "CARD_LIMIT=20"
set "RUNNER_LOG=logs\crawler_runner.log"

set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"

echo [%date% %time%] Starting crawler >> "%RUNNER_LOG%"

"%PYTHON_CMD%" -X utf8 main.py >> "%RUNNER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Crawler failed with exit code %ERRORLEVEL% >> "%RUNNER_LOG%"
    exit /b 1
)

"%PYTHON_CMD%" -X utf8 enrich_articles.py --input data\exports\new_articles.csv >> "%RUNNER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Article enrichment failed with exit code %ERRORLEVEL% >> "%RUNNER_LOG%"
    exit /b 1
)

"%PYTHON_CMD%" -X utf8 generate_news_cards.py --input data\exports\new_articles.csv --limit %CARD_LIMIT% --clean >> "%RUNNER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Image generation failed with exit code %ERRORLEVEL% >> "%RUNNER_LOG%"
    exit /b 1
)

"%PYTHON_CMD%" -X utf8 scripts\sync_cms_from_csv.py >> "%RUNNER_LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] CMS sync failed with exit code %ERRORLEVEL% >> "%RUNNER_LOG%"
    exit /b 1
)

echo [%date% %time%] Finished crawler successfully >> "%RUNNER_LOG%"

exit /b 0
