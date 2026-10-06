from io import BytesIO
from shlex import quote
from pathlib import Path
from subprocess import run
from shutil import which
from pytest import mark, fixture
from json import dumps, loads
from tarfile import TarInfo, open as open_tar
from sys import platform, executable, version_info
from portablepy.launcher import file_hash, cached_python
from portablepy.bootstrap import write_setup
from portablepy.bytecode import compile_tree
from portablepy.discovery import probe
from portablepy.runtime import recipient_runtime, STANDALONE_RELEASES


@fixture
def unix_setup(tmp_path, monkeypatch):
    if platform not in ('linux', 'darwin'):
        from pytest import skip

        skip('Needs a native Unix shell and Python')
    tools = tmp_path / 'tools'
    tools.mkdir()
    for name in (
        'sh',
        'uname',
        'sha256sum',
        'shasum',
        'awk',
        'cat',
        'sed',
        'mktemp',
        'chmod',
        'mv',
        'mkdir',
        'rmdir',
        'rm',
        'tar',
        'gzip',
        'cp',
        'dirname',
    ):
        path = which(name)
        if path:
            (tools / name).symlink_to(path)
    version = '.'.join(map(str, version_info[:3]))
    series = '.'.join(map(str, version_info[:2]))
    runtime = recipient_runtime(probe(Path(executable)), series)
    download = {
        'version': version,
        'architecture': 'aarch64' if runtime['machine'] in ('aarch64', 'arm64') else 'x86_64',
        'platform': platform,
        'libc': runtime.get('libc', 'none'),
        'build': '20261003',
        'url': STANDALONE_RELEASES + f'20261003/cpython-{version}-install_only_stripped.tar.gz',
        'provider': 'astral',
    }
    archive = tmp_path / 'runtime.tar.gz'
    with open_tar(archive, 'w:gz') as tar:
        data = f'#!/bin/sh\nexec {quote(executable)} "$@"\n'.encode()
        item = TarInfo(f'python/bin/python{series}')
        item.size = len(data)
        item.mode = 0o755
        tar.addfile(item, BytesIO(data))
    download['sha256'] = file_hash(archive)
    curl = tools / 'curl'
    curl.write_text("""#!/bin/sh
while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then
        output=$2
        shift
    fi
    shift
done
printf 'download\\n' >> "$DOWNLOAD_LOG"
cp "$DOWNLOAD_FIXTURE" "$output"
""")
    curl.chmod(0o755)
    # An installed interpreter that fails the runtime probe must not prevent fallback.
    bad_python = tools / f'python{series}'
    bad_python.write_text('#!/bin/sh\nexit 1\n')
    bad_python.chmod(0o755)
    monkeypatch.setenv('PATH', str(tools))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('DOWNLOAD_FIXTURE', str(archive))
    monkeypatch.setenv('DOWNLOAD_LOG', str(tmp_path / 'downloads.log'))
    cache = tmp_path / (
        'home/Library/Application Support/portablepy' if platform == 'darwin' else 'data/portablepy'
    )
    return runtime, download, cache, archive


def bundle(root, runtime, download, compiled=False):
    root.mkdir()
    (root / 'run.py').write_text(
        'from sys import argv\nfrom json import dumps\nprint(dumps(argv[1:]))\nraise SystemExit(7)\n'
    )
    launcher = 'run.pyc' if compiled else 'run.py'
    if compiled:
        compile_tree(root / 'run.py', Path(executable), strip=True)
    (root / 'bundle.json').write_text(dumps({'runtime': runtime, 'python_download': download}))
    (root / 'bundle.json.sha256').write_text(file_hash(root / 'bundle.json'))
    write_setup(root, runtime, download, launcher)


@mark.parametrize('compiled', [False, True])
def test_unix_download_creates_relocatable_script_and_shared_cache(tmp_path, unix_setup, compiled):
    runtime, download, cache, archive = unix_setup
    script_name = 'run.command' if platform == 'darwin' else 'run.sh'
    for name in ('first app', 'second app'):
        root = tmp_path / name
        bundle(root, runtime, download, compiled)
        assert not (root / script_name).exists()
        result = run(
            ['sh', str(root / 'python-setup.sh')], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
        selected = Path(result.stdout.strip())
        assert selected.is_relative_to(cache)
        assert f'python-{download["version"]}-{download["architecture"]}' in str(selected)
        assert selected.is_file() and (root / script_name).is_file()
        assert cached_python(root) == str(selected)
        assert not (root / '.python').exists()
        helper = root / 'python-setup.sh'
        original = helper.read_text(encoding='utf-8')
        helper.write_text(
            original.replace(
                'import struct, platform, sysconfig, venv, ensurepip',
                'raise RuntimeError("unexpected discovery")',
            ),
            encoding='utf-8',
        )
        moved = tmp_path / (name + ' moved & punctuation!')
        root.rename(moved)
        arguments = ['two words', 'a&b', 'bang!']
        launched = run(
            [str(moved / script_name), *arguments], capture_output=True, text=True, timeout=30
        )
        assert launched.returncode == 7, launched.stdout + launched.stderr
        assert loads(launched.stdout) == arguments
        (moved / 'python-setup.sh').write_text(original, encoding='utf-8')
        (moved / '.portablepy-python').write_text('stale')
        recovered = run(
            [str(moved / script_name), *arguments], capture_output=True, text=True, timeout=30
        )
        assert recovered.returncode == 7, recovered.stdout + recovered.stderr
        assert loads(recovered.stdout) == arguments
        assert cached_python(moved) == str(selected)
    assert (tmp_path / 'downloads.log').read_text().splitlines() == ['download']
    assert not list(cache.glob('*.lock'))
    assert not list(cache.glob('.portablepy-runtime-*'))


@mark.parametrize('corrupt', [False, True])
def test_unix_download_rejects_traversal_and_bad_checksum(tmp_path, unix_setup, corrupt):
    runtime, download, cache, archive = unix_setup
    with open_tar(archive, 'w:gz') as tar:
        item = TarInfo('python/../../escaped.txt')
        item.size = 4
        tar.addfile(item, BytesIO(b'bad!'))
    download['sha256'] = '0' * 64 if corrupt else file_hash(archive)
    root = tmp_path / 'bundle'
    bundle(root, runtime, download)
    result = run(['sh', str(root / 'python-setup.sh')], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert ('SHA-256' if corrupt else 'Unsafe path') in result.stderr
    assert not (tmp_path / 'escaped.txt').exists()
    assert not list(cache.glob('python-*'))
    assert not list(cache.glob('.portablepy-runtime-*'))
    assert not (root / 'run.sh').exists() and not (root / 'run.command').exists()


@mark.parametrize('target', ['linux', 'darwin'])
def test_unix_helper_is_rendered_without_generating_launch_script(tmp_path, target):
    runtime = recipient_runtime(probe(Path(executable)), '3.14')
    runtime['platform'] = target
    download = {
        'version': '3.14.8',
        'architecture': 'aarch64',
        'platform': target,
        'libc': 'gnu' if target == 'linux' else 'none',
        'build': '20261003',
        'url': STANDALONE_RELEASES + 'runtime-install_only_stripped.tar.gz',
        'sha256': 'a' * 64,
    }
    name = write_setup(tmp_path, runtime, download, 'run.pyc')
    text = (tmp_path / name).read_text()
    assert '@EXPECTED@' not in text and '@CACHE_SUFFIX@' not in text
    assert 'run.pyc' in text
    assert 'python-3.14.8-aarch64' in text
    assert not (tmp_path / 'run.command').exists() and not (tmp_path / 'run.sh').exists()
