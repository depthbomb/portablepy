"""Build portable application bundles from a configuration file."""

from pathlib import Path
from typing import Annotated
from argly import command, Argument
from portablepy.builder import build_bundle
from portablepy.config import resolve_options


@command('build', summary='Build a verified archive using portablepy.toml.')
def build(
    config: Annotated[
        Path | None, Argument(help='Config file; defaults to the nearest portablepy.toml.')
    ] = None,
) -> int:
    path = build_bundle(resolve_options(config))
    print(f'Created {path} ({path.stat().st_size:,} bytes)')
    return 0
