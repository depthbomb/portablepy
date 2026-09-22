from json import loads
from os import environ
from pytest import mark
from pathlib import Path
from subprocess import run
from zipfile import ZipFile
from tarfile import open as open_tar
from portablepy.models import BuildOptions
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle
from portablepy.bytecode import compile_tree
from portablepy.shortcuts import write_shortcut
from portablepy.discovery import discover, probe
from sys import platform, executable, version_info


@mark.parametrize('status', [0, 7])
@mark.parametrize('compiled', [False, True])
def test_native_shortcut_relocates_and_preserves_arguments(tmp_path, status, compiled):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'run.py').write_text(
        'from sys import argv, exit\nfrom json import dumps\n'
        f'print(dumps(argv[1:]))\nexit({status})\n'
    )
    if compiled:
        compile_tree(original / 'run.py', Path(executable), strip=True)
    name = write_shortcut(original, probe(Path(executable)), compiled=compiled)
    moved = tmp_path / 'moved with spaces & punctuation!'
    original.rename(moved)
    arguments = ['two words', 'a&b', 'bang!', 'plain']
    if platform == 'win32':
        shell = environ.get('COMSPEC', 'cmd.exe')
        quoted = ' '.join(f'"{value}"' for value in (str(moved / name), *arguments))
        command = f'"{shell}" /d /s /c "{quoted}"'
    else:
        command = [str(moved / name), *arguments]
    result = run(command, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == status, result.stdout + result.stderr
    assert loads(result.stdout.splitlines()[0]) == arguments
    assert ('Application failed' in result.stdout) == bool(status)


@mark.parametrize(
    'target,name', [('win32', 'run.cmd'), ('darwin', 'run.command'), ('linux', 'run.sh')]
)
@mark.parametrize('suffix', ['.zip', '.tar.gz'])
def test_archives_include_verified_shortcut_and_unix_permissions(
    tmp_path, monkeypatch, target, name, suffix
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
    assert name in manifest['files']
    member = 'bundle/' + name
    if suffix == '.zip':
        with ZipFile(archive_path) as archive:
            content = archive.read(member)
            if target != 'win32':
                assert (archive.getinfo(member).external_attr >> 16) & 0o777 == 0o755
    else:
        with open_tar(archive_path) as archive:
            stream = archive.extractfile(member)
            assert stream is not None
            content = stream.read()
            if target != 'win32':
                assert archive.getmember(member).mode == 0o755
    assert b'run.py' in content
    assert (b'\r\n' in content) == (target == 'win32')


def test_free_threaded_shortcuts_select_free_threaded_python(tmp_path):
    for target in ('win32', 'darwin', 'linux'):
        name = write_shortcut(
            tmp_path, {'platform': target, 'version': list(version_info[:2]), 'free_threaded': True}
        )
        assert '.'.join(map(str, version_info[:2])) + 't' in (tmp_path / name).read_text()


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
