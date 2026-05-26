@echo off
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"
if "%CARD_LIMIT%"=="" set "CARD_LIMIT=20"

set "PYTHON_CMD=python"
if exist "detai1\Scripts\python.exe" set "PYTHON_CMD=detai1\Scripts\python.exe"

echo [%date% %time%] Starting crawler >> "logs\crawler.log"

"%PYTHON_CMD%" -X utf8 main.py >> "logs\crawler.log" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Crawler failed with exit code %ERRORLEVEL% >> "logs\crawler.log"
    exit /b 1
)

"%PYTHON_CMD%" -X utf8 enrich_articles.py --input data\exports\new_articles.csv >> "logs\crawler.log" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Article enrichment failed with exit code %ERRORLEVEL% >> "logs\crawler.log"
    exit /b 1
)

"%PYTHON_CMD%" -X utf8 generate_news_cards.py --input data\exports\new_articles.csv --limit %CARD_LIMIT% --clean >> "logs\crawler.log" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Image generation failed with exit code %ERRORLEVEL% >> "logs\crawler.log"
    exit /b 1
)

echo [%date% %time%] Finished crawler successfully >> "logs\crawler.log"

exit /b 0
