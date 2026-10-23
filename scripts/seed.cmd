@echo off
rem Rebuild demo data: seed.cmd [--reset]
setlocal
if "%DATACLAW_PYTHON%"=="" (set "PY=python") else (set "PY=%DATACLAW_PYTHON%")
pushd "%~dp0..\backend"
"%PY%" -m app.seed %*
popd
