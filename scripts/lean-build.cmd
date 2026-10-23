@echo off
rem Build lean single binary into lean\dataclaw.exe
cd /d "%~dp0..\lean"
go build -o dataclaw.exe .
echo Built: lean\dataclaw.exe
