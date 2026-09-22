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
    'target',
    '.env',
    '.env.*',
    '.portablepy-publish-*',
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


def copy_sources(source: Path, destination: Path, excludes=(), *, paths=None):
    destination.mkdir(parents=True, exist_ok=True)
    if paths is None:
        paths = [source] if source.is_file() else selected_files(source, excludes)
    for path in paths:
        base = source.parent if source.is_file() else source
        relative = path.relative_to(base)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, target)


def data_files(specifications, base: Path):
    """Map writable destinations to their initial contents, without copying anything."""
    result: dict[PurePosixPath, Path] = {}
    for specification in specifications:
        source_text, separator, destination = specification.partition('=')
        if not separator or not source_text:
            raise ValueError('--include uses SOURCE=data/DESTINATION')
        relative = portable_path(destination)
        if len(relative.parts) < 2 or relative.parts[0] != 'data':
            raise ValueError('Included writable files must have a destination under data/')
        source = (base / Path(source_text).expanduser()).resolve()
        if not source.exists():
            raise ValueError(f'Included path does not exist: {source}')
        paths = selected_files(source) if source.is_dir() else (source,)
        for path in paths:
            target = relative / path.relative_to(source) if source.is_dir() else relative
            if any(
                target == name or target in name.parents or name in target.parents
                for name in result
            ):
                raise ValueError(f'Included destinations overlap: {target}')
            result[target] = path
    return result


def include_data(specifications, base: Path, bundle: Path):
    seeds = {}
    for destination, source in data_files(specifications, base).items():
        relative = Path('seeds', *destination.parts[1:])
        target = bundle / relative
        if target.exists():
            raise ValueError(f'Included destinations overlap: {destination}')
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)
        seeds[destination.as_posix()] = relative.as_posix()
    return seeds
