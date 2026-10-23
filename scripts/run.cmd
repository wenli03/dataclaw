@echo off
rem DataClaw: build frontend if needed, then start API on port 8787
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
