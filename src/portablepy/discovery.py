"""Prefer package metadata; infer loose-script imports from the selected environment."""

from json import loads
from pathlib import Path
from subprocess import run
from sys import executable
from tomllib import loads as load_toml
from portablepy.files import selected_files
from ast import walk, parse, Import, ImportFrom
from portablepy.models import Discovery, BuildOptions

PROBE = """
from sys import version_info, implementation, platform, stdlib_module_names
from json import dumps
from struct import calcsize
from platform import machine
from sysconfig import get_config_var
from importlib.util import MAGIC_NUMBER
from importlib.metadata import packages_distributions, version
mapping = packages_distributions()
versions = {}
for names in mapping.values():
    for name in names:
        if name not in versions:
            versions[name] = version(name)
print(dumps({
    'implementation': implementation.name,
    'version': list(version_info[:2]),
    'platform': platform,
    'machine': machine().lower(),
    'bits': calcsize('P') * 8,
    'free_threaded': bool(get_config_var('Py_GIL_DISABLED')),
    'cache_tag': implementation.cache_tag,
    'magic': MAGIC_NUMBER.hex(),
    'stdlib': sorted(stdlib_module_names),
    'distributions': mapping,
    'versions': versions,
}))
"""


def find_python(source: Path, explicit):
    if explicit is not None:
        path = explicit.expanduser().absolute()
        if not path.is_file():
            raise ValueError(f'Python interpreter does not exist: {path}')
        return path
    base = source if source.is_dir() else source.parent
    for relative in ('.venv/Scripts/python.exe', '.venv/bin/python'):
        path = base / relative
        if path.is_file():
            return path.absolute()
    return Path(executable).absolute()


def probe(python: Path):
    result = run([str(python), '-I', '-c', PROBE], capture_output=True, text=True, check=True)
    data = loads(result.stdout)
    if data['implementation'] != 'cpython' or data['version'] < [3, 14]:
        raise ValueError('Select CPython 3.14 or later with --python')
    return data


def scan_imports(source: Path, runtime: dict, excludes=()):
    base = source if source.is_dir() else source.parent
    paths = list(selected_files(base, excludes)) if source.is_dir() else [source]
    local = {}
    for root in (base, base / 'src'):
        if root.is_dir():
            for path in root.iterdir():
                if path.is_dir() and not path.name.startswith('.'):
                    local[path.name] = path
                elif path.suffix == '.py':
                    local[path.stem] = path
    imports = set()
    visited = set()
    while paths:
        path = paths.pop()
        if path in visited:
            continue
        visited.add(path)
        if path.suffix != '.py':
            continue
        try:
            tree = parse(path.read_bytes(), filename=str(path))
        except SyntaxError as error:
            raise ValueError(f'Cannot inspect {path}: {error}') from error
        found: set[str] = set()
        for node in walk(tree):
            if isinstance(node, Import):
                found.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split('.')[0])
        imports.update(found)
        for name in found & local.keys():
            dependency = local[name]
            paths.extend(
                selected_files(dependency, excludes) if dependency.is_dir() else [dependency]
            )
    external = imports - local.keys() - set(runtime['stdlib']) - {'__future__'}
    requirements, unresolved = set(), []
    for name in sorted(external):
        candidates = runtime['distributions'].get(name, [])
        if len(candidates) != 1:
            unresolved.append(name)
        else:
            distribution = candidates[0]
            requirements.add(f'{distribution}=={runtime["versions"][distribution]}')
    return sorted(requirements), unresolved


def discover(options: BuildOptions) -> Discovery:
    source = options.source.expanduser().resolve()
    if not source.exists():
        raise ValueError(f'Source does not exist: {source}')
    python = find_python(source, options.python)
    runtime = probe(python)
    files = [path.expanduser().resolve() for path in options.requirement_files]
    mode = 'script' if source.is_file() else 'directory'
    if source.suffix == '.whl':
        mode = 'wheel'
    elif source.is_dir():
        project_file = source / 'pyproject.toml'
        if project_file.is_file():
            project = load_toml(project_file.read_text(encoding='utf-8'))
            if 'project' in project or 'build-system' in project:
                mode = 'project'
        elif (source / 'setup.py').is_file() or (source / 'setup.cfg').is_file():
            mode = 'project'
    requirements = list(options.requirements)
    unresolved = []
    if mode in ('directory', 'script'):
        default = (source if source.is_dir() else source.parent) / 'requirements.txt'
        if not files and default.is_file():
            files.append(default)
        if not files and not requirements:
            requirements, unresolved = scan_imports(source, runtime, options.excludes)
    for path in files:
        if not path.is_file():
            raise ValueError(f'Requirements file does not exist: {path}')
    return Discovery(source, python, runtime, mode, requirements, files, unresolved)
