from json import loads
from ast import parse
from pytest import mark
from pathlib import Path
from sys import executable
from subprocess import run
from zipfile import ZipFile
from tarfile import open as open_tar
from portablepy.models import BuildOptions
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle
from portablepy.bytecode import compile_tree
from portablepy.discovery import discover
from portablepy import launcher
from portablepy.launcher import cached_python, remember_python


@mark.parametrize('target', ['win32', 'darwin', 'linux'])
@mark.parametrize('suffix', ['.zip', '.tar.gz'])
def test_archives_use_python_launcher_without_shell_shortcuts(
    tmp_path, monkeypatch, target, suffix
):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'main.py').write_text('print(123)\n')
    options = BuildOptions(source, ('python', 'main.py'), tmp_path / ('bundle' + suffix))
    discovery = discover(options)
    discovery.runtime['platform'] = target
    monkeypatch.setattr('portablepy.builder.discover', lambda _: discovery)
    monkeypatch.setattr('portablepy.builder.run', lambda *args, **kwargs: None)
    archive_path = build_bundle(options)
    manifest = verify_bundle(archive_path)
    assert 'run.py' in manifest['files']
    assert not {'run.cmd', 'run.command', 'run.sh'} & manifest['files'].keys()
    if suffix == '.zip':
        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            content = archive.read('bundle/README.txt')
    else:
        with open_tar(archive_path) as archive:
            names = archive.getnames()
            stream = archive.extractfile('bundle/README.txt')
            assert stream is not None
            content = stream.read()
    assert not {'bundle/run.cmd', 'bundle/run.command', 'bundle/run.sh'} & set(names)
    assert b'python run.py' in content
    assert all(name.encode() not in content for name in ('run.cmd', 'run.command', 'run.sh'))


@mark.parametrize(
    'mode,strip', [('none', False), ('app', False), ('app', True), ('all', False), ('all', True)]
)
def test_launcher_compilation_scope_and_source_retention(tmp_path, monkeypatch, mode, strip):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'main.py').write_text('print(123)\n')
    validated = []
    monkeypatch.setattr(
        'portablepy.builder.run', lambda command, **kwargs: validated.append(command)
    )
    output = build_bundle(
        BuildOptions(
            source,
            ('python', 'main.py'),
            tmp_path / 'bundle.zip',
            compile_mode=mode,
            strip_source=strip,
        )
    )
    manifest = verify_bundle(output)
    compiled = mode == 'all'
    launcher = 'run.pyc' if compiled else 'run.py'
    assert ('run.pyc' in manifest['files']) == compiled
    assert ('run.py' in manifest['files']) == (not compiled or not strip)
    assert Path(validated[0][2]).name == launcher
    with ZipFile(output) as archive:
        archive.extractall(tmp_path / 'extracted')
    root = tmp_path / 'extracted/bundle'
    assert f'python {launcher}' in (root / 'README.txt').read_text()
    result = run(
        [executable, '-I', str(root / launcher), '--portable-info'],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert loads(result.stdout)['compile'] == mode


def test_compilation_preserves_assertions_and_docstrings(tmp_path, monkeypatch):
    source = tmp_path / 'run.py'
    source.write_text(
        '"""preserved docstring"""\nassert __doc__ == "preserved docstring"\nassert False, "assertion preserved"\n'
    )
    monkeypatch.setenv('PYTHONOPTIMIZE', '2')
    compile_tree(source, Path(executable), strip=True)
    result = run(
        [executable, '-I', str(source.with_suffix('.pyc'))],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert 'AssertionError: assertion preserved' in result.stderr


def test_source_launcher_can_bootstrap_from_older_python():
    parse(Path(launcher.__file__).read_text(encoding='utf-8'), feature_version=(3, 9))


@mark.parametrize(
    'change', ['manifest', 'executable', 'base', 'config', 'new_config', 'removed', 'malformed']
)
def test_python_selection_cache_invalidates_changed_files(tmp_path, monkeypatch, change):
    root = tmp_path / 'bundle'
    root.mkdir()
    (root / 'bundle.json').write_text('{}')
    python = tmp_path / 'runtime/bin/python'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'python')
    base = tmp_path / 'base-python'
    base.write_bytes(b'base')
    config = python.parent.parent / 'pyvenv.cfg'
    config.write_text('home = base')
    monkeypatch.setattr(launcher, 'executable', str(python))
    monkeypatch.setattr(launcher.sys, '_base_executable', str(base))
    remember_python(root)
    assert cached_python(root) == str(python)

    moved = tmp_path / 'moved bundle'
    root.rename(moved)
    assert cached_python(moved) == str(python)
    if change == 'removed':
        python.unlink()
    else:
        path = {
            'manifest': moved / 'bundle.json',
            'executable': python,
            'base': base,
            'config': config,
            'new_config': python.parent / 'pyvenv.cfg',
            'malformed': moved / '.portablepy-python',
        }[change]
        path.write_text('changed')
    assert cached_python(moved) is None


@mark.parametrize('compiled', [False, True])
def test_runtime_handoff_starts_application_and_reuses_selection(tmp_path, monkeypatch, compiled):
    from subprocess import run as launch_process
    from sys import version_info

    source = tmp_path / 'source'
    source.mkdir()
    (source / 'main.py').write_text(
        'from sys import argv\nfrom json import dumps\nprint(dumps(argv[1:]))\nraise SystemExit(7)\n'
    )
    download = {
        'version': '.'.join(map(str, version_info[:3])),
        'architecture': '64',
        'libc': 'gnu',
        'url': 'https://www.python.org/ftp/python/unavailable.zip',
        'sha256': 'a' * 64,
    }
    monkeypatch.setattr('portablepy.discovery.resolve_runtime', lambda *_args: download)
    monkeypatch.setattr('portablepy.builder.run', lambda *_args, **_kwargs: None)
    output = build_bundle(
        BuildOptions(
            source,
            ('python', 'main.py'),
            tmp_path / 'bundle.zip',
            python_version='.'.join(map(str, version_info[:2])),
            compile_mode='all' if compiled else 'none',
            strip_source=compiled,
        )
    )
    with ZipFile(output) as archive:
        archive.extractall(tmp_path / 'extracted')
    root = tmp_path / 'extracted/bundle'
    entrypoint = root / ('run.pyc' if compiled else 'run.py')
    monkeypatch.setattr(launcher, '__file__', str(entrypoint))
    monkeypatch.setattr(launcher, 'executable', str(tmp_path / 'incompatible-python'))

    def incompatible(_expected):
        raise ValueError('incompatible runtime')

    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        kwargs.update(capture_output=True, text=True, timeout=60)
        result = launch_process(command, **kwargs)
        if result.returncode == 7:
            assert loads(result.stdout.splitlines()[-1]) == arguments
        else:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    monkeypatch.setattr(launcher, 'check_runtime', incompatible)
    monkeypatch.setattr(launcher, 'run', execute)
    arguments = ['two words', 'a&b', 'bang!', 'quotes"', '--help']
    assert launcher.main(arguments) == 7
    assert len(calls) == 2
    assert cached_python(root) is not None
    calls.clear()
    assert launcher.main(arguments) == 7
    assert len(calls) == 1
    assert calls[0][1:] == ['-I', str(entrypoint), *arguments]

    # A valid selection must not skip the bundle's integrity checks.
    app = root / loads((root / 'bundle.json').read_text())['app_directory']
    (app / 'unexpected.txt').write_text('changed')
    result = launch_process(
        [calls[0][0], '-I', str(entrypoint), *arguments], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 1
    assert 'Application files do not match' in result.stdout
