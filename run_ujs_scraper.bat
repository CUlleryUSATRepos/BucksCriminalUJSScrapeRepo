@echo off
setlocal

cd /d "C:\Users\Chris Ullery\PycharmProjects\BucksCriminalUJSScrapeRepo"

echo [%date% %time%] Starting run >> scheduler_log.txt

".venv\Scripts\python.exe" main.py >> scheduler_log.txt 2>&1
if errorlevel 1 (
    echo [%date% %time%] Python run failed. >> scheduler_log.txt
    exit /b 1
)

git add ujs_criminal_bucks.csv docs\data\ujs_criminal_bucks.csv >> scheduler_log.txt 2>&1

git diff --cached --quiet
if %errorlevel%==0 (
    echo [%date% %time%] No staged CSV changes to commit. >> scheduler_log.txt
    goto end
)

git commit -m "Daily UJS data update" >> scheduler_log.txt 2>&1
if errorlevel 1 (
    echo [%date% %time%] Git commit failed. >> scheduler_log.txt
    exit /b 1
)

git push origin main >> scheduler_log.txt 2>&1
if errorlevel 1 (
    echo [%date% %time%] Git push failed. >> scheduler_log.txt
    exit /b 1
)

echo [%date% %time%] Completed successfully. >> scheduler_log.txt

:end