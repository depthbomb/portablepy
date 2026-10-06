"""Read build and inspection settings from a project-local TOML file."""

from shlex import split
from pathlib import Path
from portablepy.models import BuildOptions
from tomllib import loads, TOMLDecodeError
from portablepy.runtime import version_parts

CONFIG_NAME = 'portablepy.toml'
LIST_KEYS = {'requirement', 'requirements', 'extra', 'include', 'exclude', 'find-links'}
BOOL_KEYS = {'no-index', 'strip-source', 'replace', 'resolve'}
TEXT_KEYS = {'source', 'run', 'output', 'python', 'python-version', 'compile'}
CONFIG_KEYS = LIST_KEYS | BOOL_KEYS | TEXT_KEYS


def _validate(settings, label):
    if not isinstance(settings, dict):
        raise ValueError(f'{label}: settings must be a TOML table')

    unknown = settings.keys() - CONFIG_KEYS
    if unknown:
        raise ValueError(f'{label}: unknown settings: {", ".join(sorted(unknown))}')

    for key, value in settings.items():
        if key in LIST_KEYS:
            valid = isinstance(value, list) and all(
                isinstance(item, str) and item.strip() for item in value
            )
            expected = 'an array of nonempty strings'
        elif key in BOOL_KEYS:
            valid = type(value) is bool
            expected = 'a boolean (true or false)'
        else:
            valid = isinstance(value, str) and bool(value.strip())
            expected = 'a nonempty string'

        if not valid:
            raise ValueError(f'{label}: {key} must be {expected}')

    if settings.get('compile', 'none') not in ('none', 'app', 'all'):
        raise ValueError(f'{label}: compile must be none, app, or all')


def _config_file(explicit):
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'Configuration file does not exist or is not a file: {path}')
        return path

    start = Path.cwd()
    for folder in (start, *start.parents):
        path = folder / CONFIG_NAME
        if path.is_file():
            return path

    raise ValueError(
        f'No {CONFIG_NAME} found in {start} or its parents. '
        f"Create one with run = 'python main.py', or pass a config file path."
    )


def resolve_options(config: Path | None = None) -> BuildOptions:
    path = _config_file(config)
    try:
        settings = loads(path.read_text(encoding='utf-8'))
    except TOMLDecodeError as error:
        raise ValueError(f'Invalid TOML in {path}: {error}') from error

    profiles = settings.pop('profiles', {})
    profile = settings.pop('profile', None)
    if not isinstance(profiles, dict):
        raise ValueError(f'{path}: profiles must be a TOML table')

    if profile is not None and (not isinstance(profile, str) or not profile.strip()):
        raise ValueError(f'{path}: profile must be a nonempty string')

    _validate(settings, str(path))
    for name, values in profiles.items():
        _validate(values, f'{path} [profiles.{name}]')

    if profile is not None:
        if profile not in profiles:
            available = ', '.join(sorted(profiles)) or '(none)'
            raise ValueError(
                f'{path}: unknown profile {profile!r}; available profiles: {available}'
            )
        settings.update(profiles[profile])

    if 'run' not in settings:
        raise ValueError(f"Set run in {path}, for example: run = 'python main.py'")

    try:
        command = tuple(split(settings['run']))
    except ValueError as error:
        raise ValueError(f'{path}: invalid run command: {error}') from error

    if not command or not command[0]:
        raise ValueError(f"Set run in {path}, for example: run = 'python main.py'")

    if settings.get('strip-source', False) and settings.get('compile', 'none') == 'none':
        raise ValueError(f"{path}: strip-source = true requires compile = 'app' or 'all'")

    if 'python-version' in settings:
        version_parts(settings['python-version'])

    base = path.parent
    for key in ('source', 'output', 'python'):
        if key in settings:
            settings[key] = (base / Path(settings[key]).expanduser()).absolute()

    if 'requirement' in settings:
        settings['requirement'] = [
            str((base / Path(item).expanduser()).absolute())
            if '://' not in item and (base / Path(item).expanduser()).exists()
            else item
            for item in settings['requirement']
        ]

    if 'requirements' in settings:
        settings['requirements'] = [
            (base / Path(item).expanduser()).resolve() for item in settings['requirements']
        ]

    if 'include' in settings:
        includes = []
        for item in settings['include']:
            filename, separator, destination = item.partition('=')
            if not separator or not filename:
                raise ValueError(f'{path}: include uses SOURCE=data/DESTINATION')
            includes.append(str((base / Path(filename).expanduser()).resolve()) + '=' + destination)
        settings['include'] = includes

    if 'find-links' in settings:
        settings['find-links'] = [
            item if '://' in item else str((base / Path(item).expanduser()).resolve())
            for item in settings['find-links']
        ]

    return BuildOptions(
        source=settings.get('source', base),
        command=command,
        output=settings.get('output'),
        python=settings.get('python'),
        requirements=tuple(settings.get('requirement', ())),
        requirement_files=tuple(settings.get('requirements', ())),
        extras=tuple(settings.get('extra', ())),
        includes=tuple(settings.get('include', ())),
        excludes=tuple(settings.get('exclude', ())),
        find_links=tuple(settings.get('find-links', ())),
        no_index=settings.get('no-index', False),
        compile_mode=settings.get('compile', 'none'),
        strip_source=settings.get('strip-source', False),
        replace=settings.get('replace', False),
        profile=profile,
        config=path,
        resolve=settings.get('resolve', False),
        python_version=settings.get('python-version'),
    )
