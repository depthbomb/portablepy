from pathlib import Path
from pytest import raises
from shutil import copytree
from json import dumps, loads
from portablepy import launcher
from portablepy.models import BuildOptions
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle
from portablepy.publishing import publish_archive
from portablepy.files import data_files, include_data
from portablepy.launcher import file_hash, seed_data, contents_hash, validate_manifest


def test_seed_updates_preserve_live_files_and_add_missing_files(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'state.json').write_text('initial')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    seeds = include_data(('state.json=data/nested/state.json',), source, bundle)
    assert not (bundle / 'data').exists()
    seed_data(bundle, {'seed_files': seeds})
    state = bundle / 'data/nested/state.json'
    assert state.read_text() == 'initial'
    state.write_text('learned')
    (source / 'state.json').write_text('new default')
    (source / 'added.json').write_text('new file')
    update = tmp_path / 'update'
    update.mkdir()
    seeds = include_data(
        ('state.json=data/nested/state.json', 'added.json=data/added.json'), source, update
    )
    copytree(update, bundle, dirs_exist_ok=True)
    seed_data(bundle, {'seed_files': seeds})
    assert state.read_text() == 'learned'
    assert (bundle / 'data/added.json').read_text() == 'new file'
    assert (bundle / 'seeds/nested/state.json').read_text() == 'new default'


def test_seed_copy_failure_does_not_leave_partial_data(tmp_path, monkeypatch):
    (tmp_path / 'seed.txt').write_text('initial')

    def fail(_source, output):
        output.write(b'partial')
        raise OSError('copy failed')

    monkeypatch.setattr('portablepy.launcher.copyfileobj', fail)
    with raises(OSError, match='copy failed'):
        seed_data(tmp_path, {'seed_files': {'data/state.txt': 'seed.txt'}})
    assert not (tmp_path / 'data/state.txt').exists()
    assert not (tmp_path / '.portablepy-data.lock').exists()


def test_overlapping_data_destinations_rejected(tmp_path):
    (tmp_path / 'seed').write_text('seed')
    with raises(ValueError, match='overlap'):
        data_files(('seed=data/a', 'seed=data/a/b'), tmp_path)


def test_publish_replacement_is_complete_and_rolls_back_on_failure(tmp_path, monkeypatch):
    output = tmp_path / 'app.zip'
    sidecar = tmp_path / 'app.zip.sha256'
    output.write_bytes(b'old')
    sidecar.write_bytes(b'old checksum')
    staged = tmp_path / 'new.zip'
    staged.write_bytes(b'new')
    original = Path.replace

    def fail_archive(self, target):
        if target == output:
            raise PermissionError('archive busy')
        return original(self, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'replace', fail_archive)
        with raises(PermissionError, match='archive busy'):
            publish_archive(staged, output, replace=True)
    assert output.read_bytes() == b'old'
    assert sidecar.read_bytes() == b'old checksum'
    assert not (tmp_path / 'app.zip.lock').exists()
    publish_archive(staged, output, replace=True)
    assert output.read_bytes() == b'new'
    assert sidecar.read_text().split()[0] == file_hash(output)


def test_failed_validation_preserves_existing_archive(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'main.py').write_text('print("ok")')
    output = tmp_path / 'app.zip'
    sidecar = tmp_path / 'app.zip.sha256'
    output.write_bytes(b'old archive')
    sidecar.write_bytes(b'old checksum')

    def fail(*_args, **_kwargs):
        raise ValueError('validation failed')

    monkeypatch.setattr('portablepy.builder.run', fail)
    options = BuildOptions(source, ('python', 'main.py'), output, replace=True)
    with raises(ValueError, match='validation failed'):
        build_bundle(options)
    assert output.read_bytes() == b'old archive'
    assert sidecar.read_bytes() == b'old checksum'
    monkeypatch.setattr('portablepy.builder.run', lambda *_args, **_kwargs: None)
    build_bundle(options)
    assert verify_bundle(output)['command'] == ['python', 'main.py']


def test_rebuild_does_not_bundle_its_previous_output(tmp_path, monkeypatch):
    (tmp_path / 'main.py').write_text('print("ok")')
    output = tmp_path / 'app.zip'
    output.write_bytes(b'old archive')
    (tmp_path / 'app.zip.sha256').write_text('old checksum')
    monkeypatch.setattr('portablepy.builder.run', lambda *_args, **_kwargs: None)
    build_bundle(BuildOptions(tmp_path, ('python', 'main.py'), output, replace=True))
    manifest = verify_bundle(output)
    files = [name for name in manifest['files'] if name.startswith(manifest['app_directory'] + '/')]
    assert files == [manifest['app_directory'] + '/main.py']


def test_manifest_rejects_unsafe_seeds_and_stale_build_id():
    manifest = {
        'schema': 1,
        'name': 'app',
        'runtime': {},
        'command': ['python', 'main.py'],
        'python_command': True,
        'strip_source': False,
        'files': {'seeds/a': '0' * 64},
    }
    for destination, source in (
        ('data/../../outside', 'seeds/a'),
        ('data/a', 'seeds/missing'),
        ('data/a', '../outside'),
    ):
        with raises(ValueError, match='[Ss]eed'):
            validate_manifest(dict(manifest, seed_files={destination: source}))
    manifest['seed_files'] = {'data/a': 'seeds/a'}
    manifest['build_id'] = contents_hash(manifest)
    validate_manifest(manifest)
    manifest['command'] = ['python', 'different.py']
    with raises(ValueError, match='build ID'):
        validate_manifest(manifest)


def test_portable_info_needs_no_matching_runtime_or_writable_setup(tmp_path, monkeypatch, capsys):
    manifest = {
        'schema': 1,
        'name': 'foreign',
        'runtime': {'platform': 'different'},
        'command': ['python', 'main.py'],
        'python_command': True,
        'strip_source': False,
        'files': {},
        'dependencies': [],
    }
    manifest['build_id'] = contents_hash(manifest)
    path = tmp_path / 'bundle.json'
    path.write_text(dumps(manifest))
    (tmp_path / 'bundle.json.sha256').write_text(file_hash(path))
    monkeypatch.setitem(vars(launcher), '__file__', str(tmp_path / 'run.py'))

    def forbidden(*_args, **_kwargs):
        raise AssertionError('info must not check the host runtime or prepare an environment')

    monkeypatch.setattr(launcher, 'prepare', forbidden)
    monkeypatch.setattr(launcher, 'check_runtime', forbidden)
    assert launcher.main(['--portable-info']) == 0
    assert loads(capsys.readouterr().out)['runtime'] == {'platform': 'different'}
    assert not (tmp_path / 'data').exists() and not (tmp_path / '.venv').exists()
