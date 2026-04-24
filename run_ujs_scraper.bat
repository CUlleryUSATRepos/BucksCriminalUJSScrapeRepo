@echo off
cd /d "C:\Users\Chris Ullery\PycharmProjects\BucksCriminalUJSScrapeRepo"

".venv\Scripts\python.exe" main.py >> scheduler_log.txt 2>&1

git add ujs_criminal_bucks.csv >> scheduler_log.txt 2>&1

git diff --cached --quiet
if %errorlevel%==0 goto end

git commit -m "Daily UJS data update" >> scheduler_log.txt 2>&1
git push >> scheduler_log.txt 2>&1

:end