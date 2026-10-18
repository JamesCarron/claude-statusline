@echo off
rem Opens the Claude Code status-line config page in the browser.
rem Stdlib-only Python server on an ephemeral port; close this window to stop it.
title Status line config
python "%~dp0config_server.py" %*
if errorlevel 1 pause
