"""Prefer package metadata; infer loose-script imports from the selected environment."""

from re import sub
from json import loads
from pathlib import Path
from subprocess import run
from sys import executable
from tomllib import loads as load_toml
from portablepy.sources import trace_sources
from portablepy.entrypoints import launch_target
from portablepy.models import Discovery, BuildOptions
from portablepy.output import output_paths, default_output

PROBE = """
from sys import version_info, implementation, platform, stdlib_module_names
from json import dumps, loads
from struct import calcsize
from platform import machine
from sysconfig import get_config_var
from importlib.util import MAGIC_NUMBER
from importlib.metadata import packages_distributions, distributions
from urllib.parse import urlsplit
from urllib.request import url2pathname
from pathlib import Path
from re import sub
mapping = packages_distributions()
versions = {}
origins = {}
commands = {}
for distribution in distributions():
    name = distribution.metadata['Name']
    if not name:
        continue
    versions[name] = distribution.version
    for entry in distribution.entry_points:
        if entry.group == 'console_scripts':
            commands.setdefault(entry.name, []).append(name)
    direct = loads(distribution.read_text('direct_url.json') or '{}')
    url = urlsplit(direct.get('url', ''))
    if url.scheme != 'file':
        continue
    location = Path(url2pathname(('//' + url.netloc if url.netloc and url.netloc != 'localhost' else '') + url.path))
    if not location.exists():
        continue
    origins[sub(r'[-_.]+', '-', name).lower()] = str(location)
    if direct.get('dir_info', {}).get('editable'):
        # Some native build backends omit top_level.txt and source files from RECORD.
        source = location / 'src'
        candidates = list(source.iterdir()) if source.is_dir() else []
        candidates.append(location / name.replace('-', '_'))
        for candidate in candidates:
            module = candidate.stem if candidate.suffix == '.py' else candidate.name
            if module.isidentifier() and (candidate.is_file() or (candidate / '__init__.py').is_file()):
                names = mapping.setdefault(module, [])
                if name not in names:
                    names.append(name)
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
    'origins': origins,
    'commands': commands,
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


def distribution_requirement(name: str, runtime: dict):
    origin = runtime.get('origins', {}).get(sub(r'[-_.]+', '-', name).lower())
    if origin and Path(origin).exists():
        return origin
    return f'{name}=={runtime["versions"][name]}'


def _requirements(imports, runtime):
    external = imports - set(runtime['stdlib']) - {'__future__'}
    requirements, unresolved = set(), []
    for name in sorted(external):
        candidates = runtime['distributions'].get(name, [])
        if len(candidates) != 1:
            unresolved.append(name)
        else:
            requirements.add(distribution_requirement(candidates[0], runtime))
    return sorted(requirements), unresolved


def scan_imports(source: Path, runtime: dict, excludes=(), *, seeds=None, ignored=()):
    _, imports = trace_sources(source, seeds, excludes, ignored)
    return _requirements(imports, runtime)


def discover(options: BuildOptions) -> Discovery:
    source = options.source.expanduser().resolve()
    if not source.exists():
        raise ValueError(f'Source does not exist: {source}')
    python = find_python(source, options.python)
    runtime = probe(python)
    files = [path.expanduser().resolve() for path in options.requirement_files]
    mode = 'script' if source.is_file() else 'directory'
    project = {}
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
    base = source if source.is_dir() else source.parent
    seeds, external_target = launch_target(options.command, base)
    owned: set[str] = set()
    if mode == 'project':
        project_name = sub(r'[-_.]+', '-', project.get('project', {}).get('name', '')).lower()
        owned.update(
            module
            for module, distributions in runtime['distributions'].items()
            if any(sub(r'[-_.]+', '-', name).lower() == project_name for name in distributions)
        )
        source_root = source / 'src'
        if source_root.is_dir():
            owned.update(
                path.stem if path.suffix == '.py' else path.name for path in source_root.iterdir()
            )
        if project_name and (source / project_name.replace('-', '_')).is_dir():
            owned.add(project_name.replace('-', '_'))
    selected = seeds or (() if external_target or mode in ('wheel', 'project') else None)
    file_reasons: dict[Path, list[str]] = {}
    import_reasons: dict[str, list[str]] = {}
    application_files, imports = trace_sources(
        source,
        selected,
        options.excludes,
        owned,
        file_reasons=file_reasons,
        import_reasons=import_reasons,
    )
    if mode in ('directory', 'script'):
        default = base / 'requirements.txt'
        if not files and default.is_file():
            files.append(default)
    if mode != 'wheel' and not files and not requirements:
        requirements, unresolved = _requirements(imports, runtime)
    if (
        external_target
        and mode in ('script', 'directory')
        and not files
        and not options.requirements
    ):
        candidates = (
            runtime['distributions'].get(external_target[1:], [])
            if external_target.startswith(':')
            else runtime.get('commands', {}).get(external_target, [])
        )
        if external_target.startswith(':') and external_target[1:] in runtime['stdlib']:
            pass
        elif len(candidates) == 1:
            requirements.append(distribution_requirement(candidates[0], runtime))
        else:
            unresolved.append(external_target.removeprefix(':'))
    for path in files:
        if not path.is_file():
            raise ValueError(f'Requirements file does not exist: {path}')
    result = Discovery(
        source,
        python,
        runtime,
        mode,
        requirements,
        files,
        unresolved,
        application_files,
        file_reasons,
        import_reasons,
    )
    output = options.output or default_output(result, options.command)
    artifacts = set(output_paths(output))
    result.application_files = tuple(
        path for path in application_files if path.resolve() not in artifacts
    )
    return result
