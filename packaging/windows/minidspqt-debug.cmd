@echo off
rem Run minidspqt with a console window and debug logging.
rem
rem minidspqt.exe is a GUI program: it has no console, so its log goes to
rem %LOCALAPPDATA%\miniDSP\minidspqt\minidspqt.log and only at WARNING level.
rem For a bug report, run this file instead - it uses the bundled console
rem interpreter, turns on -vv (USB frame traces), and keeps the window open
rem after the application exits so the output can be copied.
rem
rem Extra arguments are passed through, e.g.:  minidspqt-debug.cmd --offline
"%~dp0python.exe" -m minidspqt.cli -vv %*
echo.
echo minidspqt exited with code %ERRORLEVEL%.
pause
