"""Locate launch targets without importing or running application code."""

from pathlib import Path
from re import fullmatch


def command_target(command: tuple[str, ...]):
    if not command:
        return '', ''
    if command[0] != '{python}' and not fullmatch(r'python(?:3(?:\.\d+)?)?(?:\.exe)?', command[0]):
        return 'console', command[0]
    arguments = iter(command[1:])
    for argument in arguments:
        if argument in ('-W', '-X'):
            next(arguments, None)
        elif argument == '-c':
            return '', ''
        elif argument == '-m':
            return 'module', next(arguments, '')
        elif not argument.startswith('-'):
            return 'script', argument
    return '', ''


def launch_target(command: tuple[str, ...], base: Path):
    kind, target = command_target(command)
    if kind == 'console':
        return (), target
    if kind == 'module':
        top = target.split('.')[0]
        if not top.isidentifier():
            return (), ''
        for root in (base, base / 'src'):
            package = root / top
            script = root / (top + '.py')
            if package.is_dir():
                return (package,), ''
            if script.is_file():
                return (script,), ''
        return (), ':' + top
    if kind == 'script':
        path = (base / target.replace('{app}/', '')).resolve()
        if path.is_relative_to(base) and path.is_file():
            # Scan siblings in packages too, including dynamically discovered commands.
            return (path.parent if (path.parent / '__init__.py').is_file() else path,), ''
    return (), ''
