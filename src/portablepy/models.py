"""Build inputs shared by discovery and packaging."""

from pathlib import Path
from typing import Optional
from dataclasses import field, dataclass


@dataclass(frozen=True)
class BuildOptions:
    source: Path
    command: tuple[str, ...]
    output: Optional[Path] = None
    python: Optional[Path] = None
    requirements: tuple[str, ...] = ()
    requirement_files: tuple[Path, ...] = ()
    extras: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    find_links: tuple[str, ...] = ()
    no_index: bool = False
    compile_mode: str = 'none'
    strip_source: bool = False


@dataclass
class Discovery:
    source: Path
    python: Path
    runtime: dict
    mode: str
    requirements: list[str] = field(default_factory=list)
    requirement_files: list[Path] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    application_files: tuple[Path, ...] = ()
