@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo  自检 + 干跑（不联网、不花钱）
echo ============================================
python src\selftest.py
echo.
python src\run_all.py --mock --limit 5
echo.
echo 报告：docs\预研报告.md
pause
