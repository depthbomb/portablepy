"""Source selection and portable paths."""

from shutil import copy2
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

DEFAULT_EXCLUDES = (
    '.git',
    '.hg',
    '.svn',
    '.venv',
    'venv',
    '.tox',
    '.nox',
    '.idea',
    '.vscode',
    '__pycache__',
    '.pytest_cache',
    '.ruff_cache',
    '.mypy_cache',
    '*.egg-info',
    '*.pyc',
    '*.pyo',
    'build',
    'dist',
    '.env',
    '.env.*',
)


def portable_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or '..' in path.parts
        or '\\' in value
        or ':' in value
    ):
        raise ValueError(f'Expected a relative portable path: {value!r}')
    return path


def selected_files(root: Path, excludes=()):
    patterns = (*DEFAULT_EXCLUDES, *excludes)
    for folder, directories, names in root.walk(follow_symlinks=False):
        relative = folder.relative_to(root)

        def excluded(name, parent=relative):
            candidate = (parent / name).as_posix()
            return any(
                fnmatchcase(name, pattern) or fnmatchcase(candidate, pattern)
                for pattern in patterns
            )

        directories[:] = sorted(name for name in directories if not excluded(name))
        for name in sorted(names):
            path = folder / name
            if excluded(name):
                continue
            if path.is_symlink():
                raise ValueError(f'Symlinks must be replaced with files or excluded: {path}')
            yield path


def copy_sources(source: Path, destination: Path, excludes=()):
    destination.mkdir(parents=True, exist_ok=True)
    paths = [source] if source.is_file() else selected_files(source, excludes)
    for path in paths:
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, target)


def include_data(specification: str, base: Path, bundle: Path):
    source_text, separator, destination = specification.partition('=')
    if not separator:
        raise ValueError('--include uses SOURCE=data/DESTINATION')
    relative = portable_path(destination)
    if len(relative.parts) < 2 or relative.parts[0] != 'data':
        raise ValueError('Included writable files must have a destination under data/')
    source = (base / source_text).resolve()
    if not source.exists():
        raise ValueError(f'Included path does not exist: {source}')
    target = bundle / relative
    if target.exists():
        raise ValueError(f'Included destination already exists: {relative}')
    if source.is_dir():
        copy_sources(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)
