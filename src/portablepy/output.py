"""Default archive names for the selected application and target interpreter."""

from re import sub
from pathlib import Path
from tomllib import loads
from portablepy.models import Discovery
from portablepy.entrypoints import command_target

PLATFORM_NAMES = {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}
ARCHITECTURE_NAMES = {
    'amd64': 'x64',
    'x86_64': 'x64',
    'aarch64': 'arm64',
    'i386': 'x86',
    'i686': 'x86',
}
GENERIC_TARGETS = {'main', '__main__', 'cli', '__init__'}


def _slug(value: str):
    return sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def default_output(discovery: Discovery, command: tuple[str, ...]) -> Path:
    source = discovery.source
    project_name = source.name if source.is_dir() else source.stem
    if discovery.mode == 'wheel':
        project_name = source.name.split('-')[0]
    elif discovery.mode == 'project' and (source / 'pyproject.toml').is_file():
        metadata = loads((source / 'pyproject.toml').read_text(encoding='utf-8'))
        project_name = metadata.get('project', {}).get('name', project_name)
    project_name = _slug(project_name) or 'application'
    kind, target = command_target(command)
    if kind == 'module':
        parts = target.split('.')
        target = parts[-2] if len(parts) > 1 and parts[-1] in GENERIC_TARGETS else parts[-1]
    elif kind in ('script', 'console'):
        target = Path(target).stem
    if target in GENERIC_TARGETS:
        target = ''
    target = _slug(target)
    if target and target != project_name and not project_name.endswith('-' + target):
        project_name = (
            target if target.startswith(project_name + '-') else project_name + '-' + target
        )
    runtime = discovery.runtime
    platform = PLATFORM_NAMES.get(runtime['platform'], _slug(runtime['platform']))
    machine = runtime['machine'].lower()
    architecture = ARCHITECTURE_NAMES.get(machine, _slug(machine))
    if architecture == 'x64' and runtime['bits'] == 32:
        architecture = 'x86'
    version = ''.join(map(str, runtime['version']))
    if runtime.get('free_threaded', False):
        version += 't'
    extension = '.zip' if runtime['platform'] == 'win32' else '.tar.gz'
    return Path.cwd() / f'{project_name}-auto-{platform}-{architecture}-py{version}{extension}'


def validate_output(path: Path, *, replace=False):
    if not path.name.endswith(('.zip', '.tar.gz')):
        raise ValueError('Output must end with .zip or .tar.gz')
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f'Output must be a regular file: {path}')
    if path.exists() and not replace:
        raise ValueError(f'Output already exists: {path}')


def output_paths(path: Path):
    path = path.expanduser().resolve()
    return path, path.with_name(path.name + '.sha256'), path.with_name(path.name + '.lock')


def output_excludes(source: Path, output: Path):
    base = source if source.is_dir() else source.parent
    return tuple(
        path.relative_to(base).as_posix()
        for path in output_paths(output)
        if path.is_relative_to(base)
    )
