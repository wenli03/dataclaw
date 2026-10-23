@echo off
rem Run Go unit tests for the lean implementation
cd /d "%~dp0..\lean"
go test ./...
