@echo off
rem Wires this folder's statusline.sh into %USERPROFILE%\.claude\settings.json,
rem creates the state folder and renders a test line. Safe to re-run.
rem Pass -Force to replace an existing, different statusLine.
title Status line setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_statusline.ps1" %*
pause
