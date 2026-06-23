@echo off
rem Run on a machine WITH internet to build the offline install cache.
rem Then copy the whole folder to the offline target and double-click run.bat.
cd /d "%~dp0"
py -3 -m pip download -r requirements.txt -d wheelhouse
echo Done. wheelhouse is ready for offline transfer.
pause
