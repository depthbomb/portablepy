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
        if argument in ('-W', '-X', '--check-hash-based-pycs'):
            next(arguments, None)
        elif argument == '--':
            target = next(arguments, '')
            return ('', '') if target == '-' else ('script', target)
        elif argument == '-' or argument.startswith('-c'):
            return '', ''
        elif argument.startswith('-m'):
            return 'module', argument[2:] or next(arguments, '')
        elif not argument.startswith('-'):
            return 'script', argument
    return '', ''


def launch_target(command: tuple[str, ...], base: Path):
    kind, target = command_target(command)
    if kind == 'console':
        return (), target
    if kind == 'module':
        parts = target.split('.')
        if any(not part.isidentifier() for part in parts):
            return (), ''
        for root in (base, base / 'src'):
            package = root.joinpath(*parts)
            script = package.with_suffix('.py')
            if package.is_dir():
                return (package,), ''
            if script.is_file():
                return (script.parent if (script.parent / '__init__.py').is_file() else script,), ''
        return (), ':' + parts[0]
    if kind == 'script':
        path = (base / target.replace('{app}/', '')).resolve()
        if path.is_relative_to(base) and path.is_file():
            # Scan siblings in packages too, including dynamically discovered commands.
            return (path.parent if (path.parent / '__init__.py').is_file() else path,), ''
    return (), ''
