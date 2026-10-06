from io import BytesIO
from os import environ
from pathlib import Path
from json import dumps, loads
from subprocess import run
from pytest import mark, raises
from importlib.resources import files
from sys import executable, platform, version_info
from portablepy.models import BuildOptions
from portablepy.launcher import file_hash
from portablepy.discovery import discover, probe
from portablepy.output import default_output
from portablepy.runtime import (
    INDEX_URL,
    STANDALONE_RELEASES,
    version_parts,
    resolve_runtime,
    recipient_runtime,
)


def release(version, *, architecture='64', family='pythoncore', digest='a' * 64):
    series = '.'.join(version.split('.')[:2])
    return {
        'id': f'{family}-{series}-{architecture}',
        'sort-version': version,
        'url': f'https://www.python.org/ftp/python/{version}/python-{version}-amd64.zip',
        'hash': {'sha256': digest},
    }


def test_runtime_resolution_checks_all_pages_and_skips_prereleases(monkeypatch):
    pages = {
        INDEX_URL: {'versions': [release('3.14.8'), release('3.15.0rc1')], 'next': 'older.json'},
        'https://www.python.org/ftp/python/older.json': {
            'versions': [release('3.14.7'), release('3.14.9', family='pythonembed')],
        },
    }
    monkeypatch.setattr(
        'portablepy.runtime._open_download', lambda url: BytesIO(dumps(pages[url]).encode())
    )
    runtime = {'machine': 'AMD64', 'bits': 64}
    assert resolve_runtime('3.14', runtime)['version'] == '3.14.8'
    assert resolve_runtime('3.14.7', runtime)['version'] == '3.14.7'
    with raises(ValueError, match='No official stable'):
        resolve_runtime('3.15', runtime)


@mark.parametrize('bad', ['3', '3.14.8.1', '3.14rc1', '3.014', '3.13', 'https://example.com'])
def test_invalid_recipient_version(bad):
    with raises(ValueError, match='python-version'):
        version_parts(bad)


@mark.parametrize('field,value', [('hash', {}), ('url', 'https://example.com/python.zip')])
def test_runtime_download_requires_official_url_and_hash(monkeypatch, field, value):
    entry = release('3.14.8')
    entry[field] = value
    monkeypatch.setattr(
        'portablepy.runtime._open_download',
        lambda url: BytesIO(dumps({'versions': [entry]}).encode()),
    )
    with raises(ValueError, match='official|SHA-256'):
        resolve_runtime('3.14', {'machine': 'amd64', 'bits': 64})


def standalone(version, *, target='linux', arch='x86_64', libc='gnu', **overrides):
    major, minor, patch = map(int, version.split('.'))
    entry = {
        'name': 'cpython',
        'arch': {'family': arch, 'variant': None},
        'os': target,
        'libc': libc,
        'major': major,
        'minor': minor,
        'patch': patch,
        'prerelease': '',
        'variant': None,
        'build': '20261003',
        'url': STANDALONE_RELEASES
        + f'20261003/cpython-{version}%2B20261003-{arch}-{target}-install_only_stripped.tar.gz',
        'sha256': 'a' * 64,
    }
    entry.update(overrides)
    return entry


@mark.parametrize(
    'target,machine,arch,libc',
    [
        ('linux', 'x86_64', 'x86_64', 'gnu'),
        ('linux', 'aarch64', 'aarch64', 'musl'),
        ('darwin', 'arm64', 'aarch64', 'none'),
    ],
)
def test_standalone_selects_stable_standard_build_for_target(
    monkeypatch, target, machine, arch, libc
):
    entries = [
        standalone('3.14.7', target=target, arch=arch, libc=libc),
        standalone('3.14.8', target=target, arch=arch, libc=libc),
        standalone('3.14.9', target=target, arch=arch, libc=libc, prerelease='rc1'),
        standalone('3.14.9', target=target, arch=arch, libc=libc, variant='freethreaded'),
        standalone('3.14.9', target=target, arch=arch, libc=libc)
        | {'arch': {'family': arch, 'variant': 'v3'}},
        standalone('3.14.9', target='win32', arch=arch, libc=libc),
    ]
    monkeypatch.setattr(
        'portablepy.runtime._open_standalone_index',
        lambda: BytesIO(dumps(dict(enumerate(entries))).encode()),
    )
    runtime = {'platform': target, 'machine': machine, 'bits': 64, 'libc': libc}
    assert resolve_runtime('3.14', runtime)['version'] == '3.14.8'
    assert resolve_runtime('3.14.7', runtime)['version'] == '3.14.7'
    assert resolve_runtime('3.14', runtime)['provider'] == 'astral'
    with raises(ValueError, match='No stable Astral'):
        resolve_runtime('3.15', runtime)


@mark.parametrize(
    'field,value',
    [('url', 'https://example.com/runtime.tar.gz'), ('sha256', ''), ('build', '../escape')],
)
def test_standalone_rejects_untrusted_download_metadata(monkeypatch, field, value):
    entry = standalone('3.14.8', **{field: value})
    monkeypatch.setattr(
        'portablepy.runtime._open_standalone_index',
        lambda: BytesIO(dumps({'test': entry}).encode()),
    )
    with raises(ValueError, match='Astral'):
        resolve_runtime('3.14', {'platform': 'linux', 'machine': 'x86_64', 'bits': 64})


def test_recipient_version_does_not_change_builder_interpreter(tmp_path, monkeypatch):
    (tmp_path / 'main.py').write_text('print(123)')
    original = probe(Path(executable))
    simulated = dict(original, version=[3, 15], full_version=[3, 15, 1])
    monkeypatch.setattr('portablepy.discovery.probe', lambda python: simulated)
    monkeypatch.setattr('portablepy.discovery.resolve_runtime', lambda *args: {'version': '3.14.8'})
    options = BuildOptions(
        tmp_path, ('python', 'main.py'), python=Path(executable), python_version='3.14.8'
    )
    result = discover(options)
    assert result.python == Path(executable).absolute()
    assert result.runtime['version'] == [3, 15]
    target = recipient_runtime(result.runtime, options.python_version)
    assert target['version'] == [3, 14] and target['full_version'] == [3, 14, 8]
    assert 'magic' not in target and 'cache_tag' not in target
    assert 'py314' in default_output(result, options.command).name
    with raises(ValueError, match='Cross-version bundles'):
        recipient_runtime(result.runtime, options.python_version, compiled=True)


@mark.skipif(platform != 'win32', reason='Windows bootstrap')
@mark.parametrize('exact', [False, True])
@mark.parametrize('compiled', [False, True])
def test_windows_bootstrap_prefers_installed_python_and_preserves_arguments(
    tmp_path, monkeypatch, exact, compiled
):
    from portablepy.bytecode import compile_tree

    root = tmp_path / 'bundle with spaces & punctuation!'
    root.mkdir()
    (root / 'run.py').write_text(
        'from sys import argv\nfrom json import dumps\nprint(dumps(argv[1:]))\n'
    )
    if compiled:
        compile_tree(root / 'run.py', Path(executable), strip=True)
    (root / 'python-setup.ps1').write_bytes(
        files('portablepy').joinpath('python-setup.ps1').read_bytes()
    )
    requested = '.'.join(map(str, version_info[: 3 if exact else 2]))
    runtime = recipient_runtime(probe(Path(executable)), requested)
    manifest = {
        'runtime': runtime,
        'compile': 'all' if compiled else 'none',
        'python_download': {
            'version': requested,
            'architecture': '64',
            'url': 'https://www.python.org/ftp/python/unavailable.zip',
            'sha256': 'a' * 64,
        },
    }
    (root / 'bundle.json').write_text(dumps(manifest))
    (root / 'bundle.json.sha256').write_text(file_hash(root / 'bundle.json'))
    monkeypatch.setenv('PATH', str(Path(executable).parent) + ';' + environ.get('PATH', ''))
    arguments = ['two words', 'a&b', 'bang!', 'plain']
    setup = run(
        [
            'powershell.exe',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(root / 'python-setup.ps1'),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    selected = Path(setup.stdout.strip())
    assert selected.is_file()
    script = root / 'run.cmd'
    assert script.is_file()
    quoted = ' '.join(f'"{value}"' for value in (str(script), *arguments))
    shell = environ.get('COMSPEC', 'cmd.exe')
    result = run(f'"{shell}" /d /s /c "{quoted}"', capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert loads(result.stdout.strip()) == arguments
    assert not (root / '.python').exists()


@mark.skipif(platform != 'win32', reason='Windows bootstrap')
@mark.parametrize('corrupt', [True, False])
def test_windows_download_rejects_hash_mismatch_and_unsafe_archive(tmp_path, monkeypatch, corrupt):
    from zipfile import ZipFile

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'user-data'))
    archive = tmp_path / 'download.zip'
    with ZipFile(archive, 'w') as bundle:
        bundle.writestr('../escaped.txt', b'unsafe')
    runtime = recipient_runtime(probe(Path(executable)), '3.99')
    manifest = {
        'runtime': runtime,
        'python_download': {
            'version': '3.99.0',
            'architecture': '64',
            'url': 'https://www.python.org/ftp/python/unavailable.zip',
            'sha256': 'a' * 64 if corrupt else file_hash(archive),
        },
    }
    (tmp_path / 'bundle.json').write_text(dumps(manifest))
    (tmp_path / 'bundle.json.sha256').write_text(file_hash(tmp_path / 'bundle.json'))
    script = files('portablepy').joinpath('python-setup.ps1').read_text(encoding='utf-8')
    # Keep the real checksum and extraction code, substituting only the network transfer.
    original = 'Invoke-WebRequest -Uri $Download.url -OutFile $Archive -UseBasicParsing -TimeoutSec 60 -MaximumRedirection 0'
    fixture = str(archive).replace("'", "''")
    script = script.replace(original, f"Copy-Item -LiteralPath '{fixture}' -Destination $Archive")
    setup = tmp_path / 'python-setup.ps1'
    setup.write_text(script, encoding='utf-8')
    result = run(
        [
            'powershell.exe',
            '-NoProfile',
            '-NonInteractive',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(setup),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert ('SHA-256 check' if corrupt else 'Unsafe path') in result.stderr
    assert not (tmp_path / 'escaped.txt').exists()
    assert not (tmp_path / '.python').exists()
    assert not (tmp_path / 'run.cmd').exists()
    cache = tmp_path / 'user-data/portablepy'
    assert not list(cache.glob('*.lock'))
    assert not list(cache.glob('.portablepy-runtime-*'))


@mark.skipif(platform != 'win32', reason='Windows bootstrap')
def test_windows_shared_cache_is_reused_by_multiple_bundles(tmp_path, monkeypatch):
    from shutil import copy2
    from sys import base_prefix

    version = '.'.join(map(str, version_info[:3]))
    runtime = recipient_runtime(probe(Path(executable)), '.'.join(map(str, version_info[:2])))
    architecture = (
        'arm64' if runtime['machine'] == 'arm64' else '64' if runtime['bits'] == 64 else '32'
    )
    download = {
        'version': version,
        'architecture': architecture,
        'url': 'https://www.python.org/ftp/python/unavailable.zip',
        'sha256': 'a' * 64,
    }
    cache = tmp_path / 'user-data/portablepy'
    cached = cache / f'python-{version}-{architecture}'
    cached.mkdir(parents=True)
    copy2(executable, cached / 'python.exe')
    (cache / 'pyvenv.cfg').write_text(
        f'home = {base_prefix}\ninclude-system-site-packages = false\n'
    )
    (cached / '.portablepy-runtime.json').write_text(dumps(download))
    monkeypatch.setenv('LOCALAPPDATA', str(cache.parent))
    system = Path(environ['SystemRoot']) / 'System32'
    monkeypatch.setenv('PATH', str(system) + ';' + str(system / 'WindowsPowerShell/v1.0'))
    for name in ('first app', 'second app'):
        root = tmp_path / name
        root.mkdir()
        # A series requirement can reuse an older cached patch instead of its pinned fallback.
        manifest = {'runtime': runtime, 'python_download': dict(download, version='3.14.999')}
        (root / 'bundle.json').write_text(dumps(manifest))
        (root / 'bundle.json.sha256').write_text(file_hash(root / 'bundle.json'))
        (root / 'python-setup.ps1').write_bytes(
            files('portablepy').joinpath('python-setup.ps1').read_bytes()
        )
        result = run(
            [
                'powershell.exe',
                '-NoProfile',
                '-NonInteractive',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                str(root / 'python-setup.ps1'),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(cached / 'python.exe')
        assert (root / 'run.cmd').is_file()
        assert not (root / '.python').exists()
    assert list(cache.glob('python-*')) == [cached]
