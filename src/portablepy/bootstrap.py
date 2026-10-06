"""Render setup helpers for recipients who need another Python runtime."""

from json import dumps
from shlex import quote
from pathlib import Path
from importlib.resources import files


def setup_instructions(runtime: dict, version: str) -> str:
    if runtime['platform'] == 'win32':
        command = (
            'In PowerShell:\n'
            '    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./python-setup.ps1\n'
            '    if ($LASTEXITCODE -eq 0) {\n'
            '        ./run.cmd\n'
            '    }\n'
        )
        script = 'run.cmd'
    else:
        script = 'run.command' if runtime['platform'] == 'darwin' else 'run.sh'
        command = f'In a terminal:\n    sh ./python-setup.sh && ./{script}\n'
    return (
        f'Required recipient Python: {version}.\n'
        'The setup helper selects a matching installed Python first.\n'
        'If none is available, it reuses or downloads a verified runtime in your user application data.\n'
        'The download needs internet access once; later launches reuse the local runtime.\n'
        'To select or download Python, run these commands from this folder:\n\n'
        + command
        + f'\nSetup creates {script} for subsequent launches, including after moving this folder.\n\n'
    )


def write_setup(bundle: Path, runtime: dict, download: dict, launcher: str) -> str:
    if runtime['platform'] == 'win32':
        name = 'python-setup.ps1'
        (bundle / name).write_bytes(files('portablepy').joinpath(name).read_bytes())
        return name

    name = 'python-setup.sh'
    script = files('portablepy').joinpath(name).read_text(encoding='utf-8')
    replacements = {
        'EXPECTED': dumps(runtime, separators=(',', ':')),
        'SERIES': '.'.join(map(str, runtime['version'])),
        'VERSION': download['version'],
        'URL': download['url'],
        'SHA256': download['sha256'],
        'RUNTIME': 'python-'
        + download['version']
        + '-'
        + download['architecture']
        + ('-' + download['libc'] if runtime['platform'] == 'linux' else ''),
        'CACHE_SUFFIX': download['architecture']
        + ('-' + download['libc'] if runtime['platform'] == 'linux' else ''),
        'SYSTEM': 'Darwin' if runtime['platform'] == 'darwin' else 'Linux',
        'SCRIPT': 'run.command' if runtime['platform'] == 'darwin' else 'run.sh',
        'LAUNCHER': launcher,
    }
    for key, value in replacements.items():
        script = script.replace('@' + key + '@', quote(value))
    (bundle / name).write_text(script, encoding='utf-8', newline='\n')
    return name
