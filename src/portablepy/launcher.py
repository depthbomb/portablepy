"""Standalone launcher copied into bundles; uses only the standard library."""

from os import environ
from pathlib import Path
from shutil import rmtree
from hashlib import sha256
from struct import calcsize
from venv import EnvBuilder
from platform import machine
from json import dumps, loads
from importlib.util import MAGIC_NUMBER
from sysconfig import get_path, get_config_var
from subprocess import run, Popen, CalledProcessError
from sys import argv, platform, executable, version_info, implementation

SCHEMA_VERSION = 1
MANIFEST = 'bundle.json'
ENVIRONMENT = '.venv'
OWNER = '.portablepy-owner'
MARKER = '.portablepy-ready.json'


def file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def contents_hash(checksums):
    encoded = dumps(checksums, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode(
        'utf-8'
    )
    return sha256(encoded).hexdigest()


def load_manifest(root):
    path = root / MANIFEST
    expected = (root / f'{MANIFEST}.sha256').read_text(encoding='utf-8').strip()
    if file_hash(path) != expected:
        raise ValueError('Bundle manifest checksum failed')
    data = loads(path.read_text(encoding='utf-8'))
    validate_manifest(data)
    return data


def validate_manifest(data):
    if not isinstance(data, dict) or data.get('schema') != SCHEMA_VERSION:
        raise ValueError('Unsupported bundle format')
    if (
        not isinstance(data.get('name'), str)
        or not isinstance(data.get('runtime'), dict)
        or not isinstance(data.get('command'), list)
        or not data['command']
        or any(not isinstance(item, str) for item in data['command'])
        or type(data.get('python_command')) is not bool
        or type(data.get('strip_source')) is not bool
        or not isinstance(data.get('files'), dict)
    ):
        raise ValueError('Invalid bundle manifest')
    for name, checksum in data['files'].items():
        if (
            not isinstance(name, str)
            or not name
            or not Path(name).parts
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in '0123456789abcdef' for character in checksum)
        ):
            raise ValueError('Invalid file entry in bundle manifest')
    directory = data.get('app_directory')
    if directory is not None:
        if (
            not isinstance(directory, str)
            or len(directory) != 64
            or any(character not in '0123456789abcdef' for character in directory)
        ):
            raise ValueError('Invalid application directory in bundle manifest')
        prefix = directory + '/'
        checksums = {
            name.removeprefix(prefix): checksum
            for name, checksum in data['files'].items()
            if name.startswith(prefix)
        }
        if contents_hash(checksums) != directory:
            raise ValueError('Application directory does not match its contents hash')


def verify_files(root, manifest, *, include_data=False):
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError(f'Invalid bundle path: {name!r}')
        if relative.parts[0] == 'data' and not include_data:
            continue
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Bundle file points outside the bundle: {name}')
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f'Bundle checksum failed: {name}')
    directory = manifest.get('app_directory')
    if directory:
        app = root / directory
        if not app.resolve().is_relative_to(root.resolve()):
            raise ValueError('Application directory points outside the bundle')
        actual = {path.relative_to(root).as_posix() for path in app.rglob('*') if path.is_file()}
        expected_files = {name for name in manifest['files'] if name.startswith(directory + '/')}
        if actual != expected_files:
            raise ValueError('Application files do not match the manifest')


def check_runtime(expected):
    actual = {
        'implementation': implementation.name,
        'version': list(version_info[:2]),
        'platform': platform,
        'machine': machine().lower(),
        'bits': calcsize('P') * 8,
        'free_threaded': bool(get_config_var('Py_GIL_DISABLED')),
        'cache_tag': implementation.cache_tag,
        'magic': MAGIC_NUMBER.hex(),
    }
    if actual != expected:
        version = '.'.join(map(str, expected['version']))
        raise ValueError(
            f'This bundle needs CPython {version} on {expected["platform"]} {expected["machine"]} ({expected["bits"]}-bit, free-threaded={expected["free_threaded"]})'
        )


def prepare(root, manifest):
    (root / manifest.get('app_directory', 'app')).mkdir(exist_ok=True)
    (root / 'data').mkdir(exist_ok=True)
    environment = root / ENVIRONMENT
    if environment.resolve() != root.resolve() / ENVIRONMENT:
        raise ValueError('The private environment must not be a symlink or junction')
    python = environment / ('Scripts/python.exe' if platform == 'win32' else 'bin/python')
    expected = {
        'folder': str(root.resolve()),
        'python': str(Path(executable).absolute()),
        'manifest': file_hash(root / MANIFEST),
    }
    marker = environment / MARKER
    try:
        ready = loads(marker.read_text(encoding='utf-8'))
    except OSError:
        ready = None
    except ValueError:
        ready = None
    if ready == expected and python.is_file():
        return python
    lock = root / '.portablepy-setup.lock'
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as error:
        raise ValueError(
            'Another setup is running. If it was interrupted, remove .portablepy-setup.lock and retry.'
        ) from error
    try:
        with handle:
            handle.write('portablepy setup\n')
        if environment.exists():
            if not (environment / OWNER).is_file():
                raise ValueError(
                    'An unrelated .venv already exists here; rename it before running this bundle'
                )
            # Only remove the owned cache at this exact, resolved bundle path.
            if environment.resolve() != root.resolve() / ENVIRONMENT:
                raise ValueError('Private environment path changed during setup')
            rmtree(environment)
        environment.mkdir()
        (environment / OWNER).write_text('portablepy\n', encoding='utf-8')
        print('Setting up from bundled wheels...', flush=True)
        EnvBuilder(with_pip=True).create(environment)
        requirements = root / 'requirements.txt'
        if requirements.read_text(encoding='utf-8').strip():
            run(
                [
                    str(python),
                    '-I',
                    '-m',
                    'pip',
                    '--isolated',
                    'install',
                    '--no-index',
                    '--no-cache-dir',
                    '--only-binary=:all:',
                    '--require-hashes',
                    '--no-compile',
                    '--find-links',
                    str(root / 'wheels'),
                    '-r',
                    str(requirements),
                ],
                check=True,
            )
        run([str(python), '-I', '-m', 'pip', '--isolated', 'check'], check=True)
        marker.write_text(dumps(expected, indent=2) + '\n', encoding='utf-8')
    finally:
        lock.unlink(missing_ok=True)
    return python


def application_command(root, manifest, python, arguments):
    scripts = python.parent
    app = root / manifest.get('app_directory', 'app')
    replacements = {
        '{bundle}': str(root),
        '{app}': str(app),
        '{data}': str(root / 'data'),
        '{python}': str(python),
        '{bin}': str(scripts),
    }
    command = []
    for value in manifest['command']:
        for key, replacement in replacements.items():
            value = value.replace(key, replacement)
        command.append(value)
    if manifest['python_command']:
        command[0] = str(python)
        if manifest.get('prefer_installed', False):
            command.insert(1, '-P')
        if manifest['strip_source']:
            for index in range(1, len(command)):
                value = command[index]
                candidate = app / value
                if (
                    value.endswith('.py')
                    and not candidate.exists()
                    and candidate.with_suffix('.pyc').is_file()
                ):
                    command[index] = value + 'c'
    else:
        command[0] = str(scripts / command[0])
        if platform == 'win32' and not command[0].lower().endswith('.exe'):
            command[0] += '.exe'
        if not Path(command[0]).is_file():
            raise ValueError(f'Console command is not installed: {command[0]}')
    return [*command, *arguments]


def main(arguments=None):
    arguments = list(argv[1:] if arguments is None else arguments)
    root = Path(__file__).resolve().parent
    try:
        manifest = load_manifest(root)
        check_runtime(manifest['runtime'])
        verify_files(root, manifest)
        if arguments == ['--portable-verify']:
            print('Bundle checksums passed (writable data is preserved).')
            return 0
        python = prepare(root, manifest)
        if arguments == ['--portable-setup']:
            return 0
        command = application_command(root, manifest, python, arguments)
        environment = dict(environ)
        environment.pop('PYTHONHOME', None)
        separator = ';' if platform == 'win32' else ':'
        app = root / manifest.get('app_directory', 'app')
        import_paths = [str(app), str(app / 'src')]
        if manifest.get('prefer_installed', False):
            variables = {'base': str(root / ENVIRONMENT), 'platbase': str(root / ENVIRONMENT)}
            import_paths[:0] = [
                get_path('purelib', vars=variables),
                get_path('platlib', vars=variables),
            ]
            for argument in command[1:]:
                script = app / argument
                if script.suffix in ('.py', '.pyc') and script.is_file():
                    import_paths.append(str(script.parent))
                    break
        environment['PYTHONPATH'] = separator.join(dict.fromkeys(import_paths))
        environment['PYTHONNOUSERSITE'] = '1'
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PATH'] = str(python.parent) + separator + environment.get('PATH', '')
        with Popen(command, cwd=app, env=environment) as child:
            while True:
                try:
                    return child.wait()
                except KeyboardInterrupt:
                    # The child shares the terminal and handles its own shutdown.
                    pass
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, CalledProcessError) as error:
        print(f'portablepy: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
