@echo off
rem DataClaw acceptance check against a running instance (default 8787)
setlocal
if "%DATACLAW_PYTHON%"=="" (set "PY=python") else (set "PY=%DATACLAW_PYTHON%")
pushd "%~dp0.."
"%PY%" tools\acceptance.py %*
popd
