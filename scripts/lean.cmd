@echo off
rem Build (if needed) and run the lean Go single-binary version on port 8788
setlocal
pushd "%~dp0..\lean"
if not exist dataclaw.exe (
  echo Building lean binary...
  go build -o dataclaw.exe .
  if errorlevel 1 (echo build failed & popd & exit /b 1)
)
popd
"%~dp0..\lean\dataclaw.exe" -addr 127.0.0.1:8788 %*
