"""Verify portable application bundles."""

from pathlib import Path
from typing import Annotated
from argly import command, Argument
from portablepy.verify import verify_bundle


@command('verify', summary='Check an archive or extracted bundle without running the application.')
def verify(bundle: Annotated[Path, Argument(help='Archive or extracted bundle directory.')]) -> int:
    manifest = verify_bundle(bundle)
    print(f'Checksums passed: {manifest["name"]}')
    return 0
