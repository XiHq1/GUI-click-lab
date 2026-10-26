@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo  1/2 假模型跑通链路
echo ============================================
python selftest.py
echo.
python probe.py --mock
echo.
echo 报告在 results\ 下最新那个文件夹里（report.html）
pause
