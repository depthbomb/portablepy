"""Inspect a configured application before building."""

from json import dumps
from pathlib import Path
from typing import Annotated
from argly import command, Argument
from portablepy.config import resolve_options
from portablepy.inspection import inspection_report


@command('inspect', summary='Explain files, dependencies, and size using portablepy.toml.')
def inspect(
    config: Annotated[
        Path | None, Argument(help='Config file; defaults to the nearest portablepy.toml.')
    ] = None,
) -> int:
    options = resolve_options(config)
    report = inspection_report(options, resolve=options.resolve)
    print(dumps(report, indent=2))
    return 1 if report['unresolved_imports'] else 0
