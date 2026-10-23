@echo off
rem Run all test suites (each in its own process / temp data dir)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test.ps1" %*
