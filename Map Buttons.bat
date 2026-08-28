@echo off
cd /d "%~dp0"
echo.
echo  MPK mini IV button mapper
echo  -------------------------
echo  Press the control it names, then Enter. Enter alone skips.
echo  Best run with your DAW CLOSED so nothing intercepts the buttons.
echo.
py -3 "%~dp0button_map.py"
echo.
echo  Results saved to button_map.json in this folder.
pause
