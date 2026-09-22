"""Read build defaults and profiles without changing the caller's working directory."""

from shlex import split
from pathlib import Path
from tomllib import loads
from typing import Optional
from portablepy.models import BuildOptions

LIST_KEYS = {'requirement', 'requirements', 'extra', 'include', 'exclude', 'find-links'}
BOOL_KEYS = {'no-index', 'strip-source', 'replace'}
TEXT_KEYS = {'source', 'run', 'output', 'python', 'compile'}
CONFIG_KEYS = LIST_KEYS | BOOL_KEYS | TEXT_KEYS


def _validate(settings, label):
    if not isinstance(settings, dict):
        raise ValueError(f'{label} must be a TOML table')
    unknown = settings.keys() - CONFIG_KEYS
    if unknown:
        raise ValueError(f'Unknown {label} settings: {", ".join(sorted(unknown))}')
    for key, value in settings.items():
        if key in LIST_KEYS:
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        elif key in BOOL_KEYS:
            valid = type(value) is bool
        else:
            valid = isinstance(value, str) and bool(value)
        if not valid:
            raise ValueError(f'Invalid {label}.{key}')
    if settings.get('compile', 'none') not in ('none', 'app', 'all'):
        raise ValueError(f'{label}.compile must be none, app, or all')


def _config_file(source, explicit):
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'Configuration file does not exist: {path}')
        return path
    start = source.expanduser().resolve() if source is not None else Path.cwd()
    if start.is_file():
        start = start.parent
    for folder in (start, *start.parents):
        path = folder / 'pyproject.toml'
        if path.is_file():
            return path
    return None


def resolve_options(
    source: Optional[Path] = None,
    *,
    profile: Optional[str] = None,
    config: Optional[Path] = None,
    **overrides,
) -> BuildOptions:
    path = _config_file(source, config)
    settings = {}
    if path is not None:
        tool = loads(path.read_text(encoding='utf-8')).get('tool', {})
        if not isinstance(tool, dict):
            raise ValueError('tool must be a TOML table')
        settings = tool.get('portablepy', {})
        if not isinstance(settings, dict):
            raise ValueError('tool.portablepy must be a TOML table')
        settings = dict(settings)
    profiles = settings.pop('profiles', {})
    if not isinstance(profiles, dict):
        raise ValueError('tool.portablepy.profiles must be a TOML table')
    _validate(settings, 'tool.portablepy')
    for name, values in profiles.items():
        _validate(values, f'tool.portablepy.profiles.{name}')
    configured = bool(settings or profiles)
    if profile is not None:
        if profile not in profiles:
            available = ', '.join(sorted(profiles)) or '(none)'
            raise ValueError(f'Unknown profile {profile!r}; available profiles: {available}')
        settings.update(profiles[profile])
    base = path.parent if path is not None else Path.cwd()
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
            if not separator:
                raise ValueError('Configured include uses SOURCE=data/DESTINATION')
            includes.append(str((base / Path(filename).expanduser()).resolve()) + '=' + destination)
        settings['include'] = includes
    if 'find-links' in settings:
        settings['find-links'] = [
            item if '://' in item else str((base / Path(item).expanduser()).resolve())
            for item in settings['find-links']
        ]
    settings.update({key: value for key, value in overrides.items() if value is not None})
    selected_source = (
        source if source is not None else settings.get('source', base if configured else Path.cwd())
    )
    return BuildOptions(
        source=Path(selected_source),
        command=tuple(split(settings.get('run', ''))),
        output=settings.get('output'),
        python=settings.get('python'),
        requirements=tuple(settings.get('requirement', ())),
        requirement_files=tuple(Path(item) for item in settings.get('requirements', ())),
        extras=tuple(settings.get('extra', ())),
        includes=tuple(settings.get('include', ())),
        excludes=tuple(settings.get('exclude', ())),
        find_links=tuple(settings.get('find-links', ())),
        no_index=settings.get('no-index', False),
        compile_mode=settings.get('compile', 'none'),
        strip_source=settings.get('strip-source', False),
        replace=settings.get('replace', False),
        profile=profile,
        config=path if configured or config is not None else None,
    )
