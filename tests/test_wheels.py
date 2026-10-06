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


@mark.parametrize('compile_mode', ['none', 'keep-source', 'strip-source'])
def test_vendored_metadata_is_preserved_without_becoming_wheel_metadata(
    wheel_factory, compile_mode
):
    vendor = 'demo_app/_vendor/helper-2.0.dist-info'
    content = (
        b'Metadata-Version: 2.4\nName: helper\nVersion: 2.0\n'
        b'Requires-Dist: remote @ https://example.invalid/helper.whl\n\n'
    )
    wheel = wheel_factory(
        extra_files={
            f'{vendor}/METADATA': content,
            f'{vendor}/RECORD': b'original vendor record\n',
            'demo_app/_vendor/helper.py': b'VALUE = 42\n',
        }
    )
    if compile_mode != 'none':
        wheel = repack_bytecode(
            wheel,
            Path(executable),
            probe(Path(executable)),
            strip=compile_mode == 'strip-source',
        )
    assert wheel_metadata(wheel)['Name'] == 'demo-app'
    with ZipFile(wheel) as archive:
        assert archive.read(f'{vendor}/METADATA') == content
        assert archive.read(f'{vendor}/RECORD') == b'original vendor record\n'


def test_vendored_metadata_still_requires_valid_record_hashes(wheel_factory, tmp_path):
    name = 'demo_app/_vendor/helper-2.0.dist-info/METADATA'
    wheel = wheel_factory(extra_files={name: b'Name: helper\nVersion: 2.0\n'})
    corrupt = tmp_path / 'corrupt.whl'
    with ZipFile(wheel) as source, ZipFile(corrupt, 'w') as target:
        for entry in source.namelist():
            target.writestr(entry, b'changed' if entry == name else source.read(entry))
    with raises(ValueError, match='RECORD mismatch'):
        wheel_metadata(corrupt)


def test_multiple_top_level_metadata_directories_are_rejected(wheel_factory):
    wheel = wheel_factory(
        extra_files={'other-2.0.dist-info/METADATA': b'Name: other\nVersion: 2.0\n'}
    )
    with raises(ValueError, match='Expected one wheel metadata'):
        wheel_metadata(wheel)
