@echo off
setlocal
cd /d "%~dp0..\.."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "tools\explanation-editor\server.py"
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "tools\explanation-editor\server.py"
  goto :end
)

echo 找不到 Python。請從 Codex 執行解析編輯器，或先安裝 Python 3。
pause

:end
endlocal
