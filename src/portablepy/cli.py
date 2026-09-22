"""Argly commands for building and checking bundles."""

from json import dumps
from sys import stderr
from pathlib import Path
from tarfile import TarError
from zipfile import BadZipFile
from subprocess import CalledProcessError
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle
from typing import Any, Optional, Annotated
from portablepy.config import resolve_options
from portablepy.inspection import inspection_report
from argly import App, Flag, Option, command, Argument


EMPTY_OPTIONS: Any = ()  # Argly accepts tuples as defaults and passes fresh lists to handlers.


@command('build', summary='Build a verified portable application archive.')
def build(
    source: Annotated[Optional[Path], Argument()] = None,
    *,
    run: Annotated[
        Optional[str], Option('--command', help='Application command, such as python -m my_app.')
    ] = None,
    profile: Annotated[
        Optional[str], Option(help='Named build profile from pyproject.toml.')
    ] = None,
    config: Annotated[
        Optional[Path], Option(help='Explicit pyproject.toml configuration file.')
    ] = None,
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
        Optional[str],
        Option(
            '--compile',
            choices=('none', 'app', 'all'),
            help='Bytecode scope; all includes wheels and launcher.',
        ),
    ] = None,
    strip_source: Annotated[
        bool, Flag(help='Remove compiled .py files; requires --compile.')
    ] = False,
    keep_source: Annotated[bool, Flag(help='Keep sources, overriding a profile.')] = False,
    use_index: Annotated[bool, Flag(help='Allow index access, overriding a profile.')] = False,
    replace: Annotated[
        bool, Flag(help='Replace an archive only after the new build passes validation.')
    ] = False,
    no_replace: Annotated[bool, Flag(help='Refuse replacement, overriding a profile.')] = False,
) -> int:
    for enabled, disabled, label in (
        (strip_source, keep_source, 'strip-source/keep-source'),
        (no_index, use_index, 'no-index/use-index'),
        (replace, no_replace, 'replace/no-replace'),
    ):
        if enabled and disabled:
            raise ValueError(f'Choose only one of --{label.replace("/", " and --")}')
    options = resolve_options(
        source,
        profile=profile,
        config=config,
        **{
            'run': run,
            'output': output,
            'python': python,
            'requirement': requirement or None,
            'requirements': requirements or None,
            'extra': extra or None,
            'include': include or None,
            'exclude': exclude or None,
            'find-links': find_links or None,
            'compile': compile_mode,
            'no-index': False if use_index else True if no_index else None,
            'strip-source': False if keep_source else True if strip_source else None,
            'replace': False if no_replace else True if replace else None,
        },
    )
    path = build_bundle(options)
    print(f'Created {path} ({path.stat().st_size:,} bytes)')
    return 0


@command('inspect', summary='Explain included files, dependencies, and estimated bundle size.')
def inspect(
    source: Annotated[Optional[Path], Argument()] = None,
    *,
    python: Annotated[Optional[Path], Option()] = None,
    run: Annotated[Optional[str], Option(help='Use the same launch command as the build.')] = None,
    output: Annotated[Optional[Path], Option('-o', help='Planned archive path.')] = None,
    profile: Annotated[Optional[str], Option(help='Named build profile.')] = None,
    config: Annotated[
        Optional[Path], Option(help='Explicit pyproject.toml configuration file.')
    ] = None,
    requirement: Annotated[list[str], Option()] = EMPTY_OPTIONS,
    requirements: Annotated[list[Path], Option()] = EMPTY_OPTIONS,
    extra: Annotated[list[str], Option()] = EMPTY_OPTIONS,
    include: Annotated[list[str], Option()] = EMPTY_OPTIONS,
    exclude: Annotated[list[str], Option()] = EMPTY_OPTIONS,
    find_links: Annotated[list[str], Option()] = EMPTY_OPTIONS,
    no_index: Annotated[bool, Flag()] = False,
    use_index: Annotated[bool, Flag()] = False,
    compile_mode: Annotated[
        Optional[str], Option('--compile', choices=('none', 'app', 'all'))
    ] = None,
    strip_source: Annotated[bool, Flag()] = False,
    keep_source: Annotated[bool, Flag()] = False,
    resolve: Annotated[
        bool,
        Flag(help='Resolve/build wheels for exact dependency details and a fuller size estimate.'),
    ] = False,
) -> int:
    if (no_index and use_index) or (strip_source and keep_source):
        raise ValueError('Choose only one of each opposing flag pair')
    options = resolve_options(
        source,
        profile=profile,
        config=config,
        **{
            'python': python,
            'run': run,
            'output': output,
            'requirement': requirement or None,
            'requirements': requirements or None,
            'extra': extra or None,
            'include': include or None,
            'exclude': exclude or None,
            'find-links': find_links or None,
            'compile': compile_mode,
            'no-index': False if use_index else True if no_index else None,
            'strip-source': False if keep_source else True if strip_source else None,
        },
    )
    report = inspection_report(options, resolve=resolve)
    print(dumps(report, indent=2))
    return 1 if report['unresolved_imports'] else 0


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
