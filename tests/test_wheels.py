from pathlib import Path
from sys import executable
from zipfile import ZipFile
from pytest import mark, raises
from portablepy.discovery import probe
from portablepy.wheels import wheel_metadata, repack_bytecode


@mark.parametrize('strip', [False, True])
def test_bytecode_wheel_updates_tags_and_records(wheel_factory, strip):
    wheel = wheel_factory()
    result = repack_bytecode(wheel, Path(executable), probe(Path(executable)), strip=strip)
    metadata = wheel_metadata(result)
    assert metadata['Name'] == 'demo-app'
    with ZipFile(result) as archive:
        names = archive.namelist()
        assert any(name.endswith('.pyc') for name in names)
        assert ('demo_app/cli.py' in names) is not strip
        if strip:
            assert 'demo_app/__init__.pyc' in names
        assert b'1portable' in archive.read('demo_app-1.0.dist-info/WHEEL')
        assert archive.read('demo_app-1.0.dist-info/licenses/LICENSE') == b'Test fixture license\n'


def test_corrupt_wheel_is_rejected(wheel_factory, tmp_path):
    wheel = wheel_factory()
    corrupt = tmp_path / 'broken.whl'
    with ZipFile(wheel) as source, ZipFile(corrupt, 'w') as target:
        for name in source.namelist():
            target.writestr(name, b'changed' if name == 'demo_app/cli.py' else source.read(name))
    with raises(ValueError, match='RECORD mismatch'):
        wheel_metadata(corrupt)


def test_direct_url_dependencies_are_not_promised_offline(wheel_factory):
    wheel = wheel_factory(requires=['remote @ https://example.invalid/package.whl'])
    with raises(ValueError, match='Direct URL'):
        wheel_metadata(wheel)
