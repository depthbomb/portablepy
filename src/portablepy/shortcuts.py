"""Generate relocatable console launchers for the target platform."""

from pathlib import Path


def write_shortcut(bundle: Path, runtime: dict, *, compiled=False) -> str:
    launcher = 'run.pyc' if compiled else 'run.py'
    version = '.'.join(map(str, runtime['version']))
    suffix = 't' if runtime['free_threaded'] else ''
    if runtime['platform'] == 'win32':
        name = 'run.cmd'
        script = f"""@echo off
setlocal DisableDelayedExpansion
where py >nul 2>nul
if errorlevel 1 goto python
py -{version}{suffix} -I "%~dp0{launcher}" %*
goto finished
:python
python -I "%~dp0{launcher}" %*
:finished
set "portablepy_status=%errorlevel%"
if "%portablepy_status%"=="0" exit /b 0
echo.
echo Application failed. Check the message above and the Python requirements in README.txt.
if "%~1"=="" pause
exit /b %portablepy_status%
"""
        (bundle / name).write_text(script, encoding='utf-8', newline='\r\n')
    else:
        name = 'run.command' if runtime['platform'] == 'darwin' else 'run.sh'
        script = f"""#!/bin/sh
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
if command -v python{version}{suffix} >/dev/null 2>&1; then
    python=python{version}{suffix}
elif command -v python3 >/dev/null 2>&1; then
    python=python3
else
    python=python
fi
"$python" -I "$bundle/{launcher}" "$@"
status=$?
if [ "$status" -ne 0 ]; then
    printf '\\nApplication failed. Check the message above and the Python requirements in README.txt.\\n'
    if [ "$#" -eq 0 ] && [ -t 0 ]; then
        printf 'Press Enter to close...'
        read -r answer
    fi
fi
exit "$status"
"""
        path = bundle / name
        path.write_text(script, encoding='utf-8', newline='\n')
        path.chmod(0o755)
    return name
