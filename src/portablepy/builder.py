"""Assemble, validate, and archive a portable application."""

from json import dumps
from pathlib import Path
from re import fullmatch
from subprocess import run
from tarfile import open as open_tar
from importlib.resources import files
from tempfile import TemporaryDirectory
from portablepy.discovery import discover
from zipfile import ZipFile, ZIP_DEFLATED
from portablepy.models import BuildOptions
from portablepy.bytecode import compile_tree
from portablepy.publishing import publish_archive
from portablepy.files import copy_sources, include_data
from portablepy.output import default_output, output_excludes, validate_output
from portablepy.launcher import MANIFEST, file_hash, contents_hash, SCHEMA_VERSION
from portablepy.wheels import collect_wheels, repack_bytecode, wheel_inventory, write_requirements

RUNTIME_FIELDS = (
    'implementation',
    'version',
    'platform',
    'machine',
    'bits',
    'free_threaded',
    'cache_tag',
    'magic',
)
INSTRUCTIONS = """Portable Python application

Extract this entire folder somewhere writable. Python itself is not included.
Run: python run.py
Extra arguments are forwarded to the application: python run.py --help

The first launch installs the bundled wheels into a private .venv without
network access. Use the matching CPython version and platform in bundle.json.
Your Python installation needs the standard venv and ensurepip modules.

Writable files live in data/. Defaults ship in seeds/ and are copied only when
missing. Extract updates into the same folder to keep your data/.
Moving the folder or changing the bundle rebuilds only the private environment.
The application directory is named with a SHA-256 hash of its files and paths.
The launcher finds it automatically; its name is recorded in bundle.json.

python run.py --portable-info    Show bundle metadata without setup
python run.py --portable-setup   Set up without starting the application
python run.py --portable-verify  Verify immutable files without starting it

Wheel versions and SHA-256 hashes are pinned in requirements.txt. Checksums
detect corruption; they are not publisher signatures. Licenses for dependencies
are retained in their wheels. Bytecode is version-specific, not encryption.
"""


def _python_command(command):
    if not command:
        raise ValueError('Provide the application command with --run')
    first = command[0]
    if any(argument in ('&&', '||', '|', '>', '<', ';') for argument in command):
        raise ValueError('Commands are argument lists, not shell scripts')
    if first == '{python}' or fullmatch(r'python(?:3(?:\.\d+)?)?(?:\.exe)?', first):
        return True
    if Path(first).name != first or '/' in first or '\\' in first:
        raise ValueError('Use python, {python}, or an installed console command as the executable')
    return False


def build_bundle(options: BuildOptions) -> Path:
    if options.compile_mode not in ('none', 'app', 'all'):
        raise ValueError('--compile must be none, app, or all')
    if options.strip_source and options.compile_mode == 'none':
        raise ValueError('--strip-source requires --compile app or --compile all')
    python_command = _python_command(options.command)
    output = options.output.expanduser().absolute() if options.output is not None else None
    if output is not None:
        validate_output(output, replace=options.replace)
    discovery = discover(options)
    if output is None:
        output = default_output(discovery, options.command)
        validate_output(output, replace=options.replace)
    if discovery.unresolved:
        raise ValueError(
            'Unresolved or ambiguous imports: '
            + ', '.join(discovery.unresolved)
            + '. Install them in the selected environment, or declare dependencies with --requirement/--requirements.'
        )
    print(f'Using {discovery.python}; dependency source: {discovery.mode}', flush=True)
    name = output.name.removesuffix('.tar.gz').removesuffix('.zip')
    if not fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
        raise ValueError('Archive name must use letters, numbers, dots, underscores, or hyphens')
    with TemporaryDirectory(prefix='portablepy-build-') as temporary:
        work = Path(temporary)
        bundle = work / name
        app = bundle / 'app'
        app.mkdir(parents=True)
        (bundle / 'data').mkdir()
        source_copy = work / 'source'
        if discovery.mode == 'project':
            copy_sources(
                discovery.source,
                source_copy,
                (*options.excludes, *output_excludes(discovery.source, output)),
            )
        else:
            source_copy.mkdir()
        copy_sources(discovery.source, app, paths=discovery.application_files)
        wheels = bundle / 'wheels'
        collect_wheels(discovery, options, wheels, source_copy)
        if options.compile_mode != 'none':
            compile_tree(app, discovery.python, strip=options.strip_source)
        if options.compile_mode == 'all':
            for wheel in sorted(wheels.glob('*.whl')):
                repack_bytecode(
                    wheel, discovery.python, discovery.runtime, strip=options.strip_source
                )
        app_directory = contents_hash(
            {
                path.relative_to(app).as_posix(): file_hash(path)
                for path in app.rglob('*')
                if path.is_file()
            }
        )
        renamed = bundle / app_directory
        if not app.resolve().is_relative_to(
            bundle.resolve()
        ) or not renamed.resolve().is_relative_to(bundle.resolve()):
            raise ValueError('Application directory must stay inside the bundle')
        app.rename(renamed)
        count = write_requirements(wheels, bundle / 'requirements.txt')
        base = discovery.source if discovery.source.is_dir() else discovery.source.parent
        seeds = include_data(options.includes, base, bundle)
        (bundle / 'run.py').write_bytes(files('portablepy').joinpath('launcher.py').read_bytes())
        (bundle / 'README.txt').write_text(INSTRUCTIONS, encoding='utf-8')
        checksums = {
            path.relative_to(bundle).as_posix(): file_hash(path)
            for path in sorted(bundle.rglob('*'))
            if path.is_file()
        }
        manifest = {
            'schema': SCHEMA_VERSION,
            'name': name,
            'app_directory': app_directory,
            'runtime': {key: discovery.runtime[key] for key in RUNTIME_FIELDS},
            'command': list(options.command),
            'python_command': python_command,
            'prefer_installed': discovery.mode in ('project', 'wheel'),
            'compile': options.compile_mode,
            'strip_source': options.strip_source,
            'files': checksums,
            'seed_files': seeds,
            'dependencies': wheel_inventory(wheels),
            'profile': options.profile,
        }
        manifest['build_id'] = contents_hash(manifest)
        (bundle / MANIFEST).write_text(dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (bundle / f'{MANIFEST}.sha256').write_text(
            file_hash(bundle / MANIFEST) + '\n', encoding='utf-8'
        )
        print(f'Validating {count} wheels in an offline environment...', flush=True)
        run([str(discovery.python), '-I', str(bundle / 'run.py'), '--portable-setup'], check=True)
        members = [*checksums, MANIFEST, f'{MANIFEST}.sha256']
        output.parent.mkdir(parents=True, exist_ok=True)
        # Publish only after validation; exclude the generated environment entirely.
        staged = work / output.name
        if output.name.endswith('.zip'):
            with ZipFile(staged, 'w', compression=ZIP_DEFLATED) as archive:
                for relative in sorted(members):
                    archive.write(bundle / relative, f'{name}/{relative}')
        else:
            with open_tar(staged, 'w:gz') as archive:
                for relative in sorted(members):
                    archive.add(bundle / relative, arcname=f'{name}/{relative}', recursive=False)
        publish_archive(staged, output, replace=options.replace)
    return output
