"""Argly commands for building and checking bundles."""

from json import dumps
from sys import stderr
from shlex import split
from pathlib import Path
from tarfile import TarError
from zipfile import BadZipFile
from portablepy.discovery import discover
from subprocess import CalledProcessError
from portablepy.models import BuildOptions
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle
from typing import Any, Optional, Annotated
from argly import App, Flag, Option, command, Argument


EMPTY_OPTIONS: Any = ()  # Argly accepts tuples as defaults and passes fresh lists to handlers.


@command('build', summary='Build a verified portable application archive.')
def build(
    source: Annotated[Path, Argument()],
    *,
    run: Annotated[str, Option('--command', help='Application command, such as python -m my_app.')],
    output: Annotated[
        Optional[Path],
        Option(
            '-o',
            help='Archive path; defaults to a platform-specific name in the current directory.',
        ),
    ] = None,
    python: Annotated[
        Optional[Path], Option(help='Target interpreter; defaults to the project .venv.')
    ] = None,
    requirement: Annotated[
        list[str], Option(help='Additional package requirement.')
    ] = EMPTY_OPTIONS,
    requirements: Annotated[list[Path], Option(help='Requirements file.')] = EMPTY_OPTIONS,
    extra: Annotated[list[str], Option(help='Packaged application extra.')] = EMPTY_OPTIONS,
    include: Annotated[
        list[str], Option(help='Seed file or directory: SOURCE=data/DESTINATION.')
    ] = EMPTY_OPTIONS,
    exclude: Annotated[list[str], Option(help='Source exclusion glob.')] = EMPTY_OPTIONS,
    find_links: Annotated[
        list[str], Option(help='Local wheel directory or package listing URL.')
    ] = EMPTY_OPTIONS,
    no_index: Annotated[bool, Flag(help='Resolve from local packages only.')] = False,
    compile_mode: Annotated[
        str,
        Option(
            '--compile', choices=('none', 'app', 'all'), help='Bytecode scope; all includes wheels.'
        ),
    ] = 'none',
    strip_source: Annotated[
        bool, Flag(help='Remove compiled .py files; requires --compile.')
    ] = False,
) -> int:
    options = BuildOptions(
        source,
        tuple(split(run)),
        output,
        python,
        tuple(requirement),
        tuple(requirements),
        tuple(extra),
        tuple(include),
        tuple(exclude),
        tuple(find_links),
        no_index,
        compile_mode,
        strip_source,
    )
    path = build_bundle(options)
    print(f'Created {path} ({path.stat().st_size:,} bytes)')
    return 0


@command('inspect', summary='Show the interpreter and dependency discovery results.')
def inspect(
    source: Annotated[Path, Argument()],
    *,
    python: Annotated[Optional[Path], Option()] = None,
    run: Annotated[str, Option(help='Use the same launch command as the build.')] = '',
    exclude: Annotated[list[str], Option()] = EMPTY_OPTIONS,
) -> int:
    found = discover(
        BuildOptions(source, tuple(split(run)), Path('unused.zip'), python, excludes=tuple(exclude))
    )
    print(
        dumps(
            {
                'source': str(found.source),
                'python': str(found.python),
                'mode': found.mode,
                'runtime': {
                    key: value
                    for key, value in found.runtime.items()
                    if key not in ('stdlib', 'distributions', 'versions', 'origins', 'commands')
                },
                'inferred_requirements': found.requirements,
                'requirement_files': [str(path) for path in found.requirement_files],
                'unresolved_imports': found.unresolved,
                'application_files': [
                    path.relative_to(
                        found.source if found.source.is_dir() else found.source.parent
                    ).as_posix()
                    for path in found.application_files
                ],
            },
            indent=2,
        )
    )
    return 1 if found.unresolved else 0


@command('verify', summary='Check an archive or extracted bundle without running the application.')
def verify(bundle: Annotated[Path, Argument()]) -> int:
    manifest = verify_bundle(bundle)
    print(f'Checksums passed: {manifest["name"]}')
    return 0


def main() -> int:
    try:
        return App.discover('portablepy', 'portablepy.cli').run()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TarError, BadZipFile, CalledProcessError) as error:
        print(f'portablepy: {error}', file=stderr)
        return 1
