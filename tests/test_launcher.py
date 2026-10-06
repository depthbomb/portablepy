from json import loads
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
