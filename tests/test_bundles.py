from os import environ
from shutil import copy2
from subprocess import run
from sys import executable
from zipfile import ZipFile
from pytest import mark, raises
from tarfile import open as open_tar
from portablepy.models import BuildOptions
from portablepy.builder import build_bundle
from portablepy.verify import verify_bundle


def launch(root, *arguments, expected=0):
    environment = dict(environ, HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    result = run(
        [executable, '-I', str(root / 'run.py'), *arguments],
        cwd=root.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return result.stdout + result.stderr


def extract(path, destination):
    if path.name.endswith('.zip'):
        with ZipFile(path) as archive:
            assert not any('/.venv/' in name for name in archive.namelist())
            archive.extractall(destination)
    else:
        with open_tar(path, 'r:gz') as archive:
            archive.extractall(destination, filter='data')
    return next(destination.iterdir())


@mark.parametrize('suffix,strip', [('.zip', False), ('.tar.gz', True)])
def test_script_bundle_relocates_preserves_data_and_checks_tampering(tmp_path, suffix, strip):
    source = tmp_path / 'application'
    source.mkdir()
    (source / 'main.py').write_text(
        "from sys import argv\nfrom pathlib import Path\npath = Path(argv[1])\nprint(path.read_text(), argv[2:])\npath.write_text('learned')\n"
    )
    (source / 'seed.txt').write_text('initial')
    (source / '.env').write_text('excluded')
    output = build_bundle(
        BuildOptions(
            source,
            ('python', 'main.py', '{data}/state.txt'),
            tmp_path / ('bundle' + suffix),
            includes=('seed.txt=data/state.txt',),
            compile_mode='app',
            strip_source=strip,
            no_index=True,
        )
    )
    manifest = verify_bundle(output)
    assert not any('.env' in name for name in manifest['files'])
    assert (manifest['app_directory'] + '/main.py' in manifest['files']) is not strip
    extracted = tmp_path / 'extracted'
    extracted.mkdir()
    root = extract(output, extracted)
    assert "initial ['extra']" in launch(root, 'extra')
    verify_bundle(root)
    assert 'Setting up' not in launch(root)
    moved = extracted / 'moved with spaces'
    assert root.resolve().is_relative_to(extracted.resolve()) and moved.resolve().is_relative_to(
        extracted.resolve()
    )
    root.rename(moved)
    assert 'learned' in launch(moved)
    assert (moved / 'data/state.txt').read_text() == 'learned'
    (moved / 'requirements.txt').write_text('tampered')
    assert 'checksum failed' in launch(moved, expected=1)


@mark.parametrize('command', [('python', '-m', 'demo_app'), ('demo-command',)])
def test_wheel_bundle_installs_stripped_bytecode_and_runs_entry_points(
    tmp_path, wheel_factory, command: tuple[str, ...]
):
    wheel = wheel_factory()
    output = build_bundle(
        BuildOptions(
            wheel,
            command,
            tmp_path / 'wheel-app.zip',
            no_index=True,
            compile_mode='all',
            strip_source=True,
        )
    )
    manifest = verify_bundle(output)
    assert len([name for name in manifest['files'] if name.endswith('.whl')]) == 1
    folder = tmp_path / 'unpacked'
    folder.mkdir()
    root = extract(output, folder)
    assert 'installed hello' in launch(root, 'hello')
    assert 'Checksums' not in launch(root, '--portable-setup')
    assert 'checksums passed' in launch(root, '--portable-verify')


def test_build_refuses_to_overwrite_archive(tmp_path):
    output = tmp_path / 'app.zip'
    output.write_bytes(b'keep')
    with raises(ValueError, match='already exists'):
        build_bundle(BuildOptions(tmp_path, ('python', 'app.py'), output))
    assert output.read_bytes() == b'keep'


def test_archive_verification_rejects_unlisted_files(tmp_path):
    path = tmp_path / 'bundle.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('../escape.txt', 'bad')
    with raises(ValueError, match='portable path'):
        verify_bundle(path)


def test_transitive_dependencies_are_collected_and_installed_offline(tmp_path, wheel_factory):
    wheel_factory('demo_dependency')
    wheel = wheel_factory(
        requires=['demo-dependency==1.0'],
        extra_files={
            'demo_app/cli.py': b"from demo_dependency import VALUE\ndef main():\n    print('dependency', VALUE)\n    return 0\n",
        },
    )
    output = build_bundle(
        BuildOptions(
            wheel,
            ('python', '-m', 'demo_app'),
            tmp_path / 'transitive.zip',
            find_links=(str(tmp_path),),
            no_index=True,
        )
    )
    manifest = verify_bundle(output)
    assert len([name for name in manifest['files'] if name.endswith('.whl')]) == 2
    destination = tmp_path / 'transitive'
    destination.mkdir()
    assert 'dependency installed' in launch(extract(output, destination))


def test_packaged_project_imports_built_code_before_source_copy(
    tmp_path, wheel_factory, monkeypatch
):
    wheel = wheel_factory()
    source = tmp_path / 'generated-project'
    source.mkdir()
    (source / 'pyproject.toml').write_text('[project]\nname="demo-app"\nversion="1.0"\n')
    package = source / 'src/demo_app'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text("raise RuntimeError('unbuilt source')\n")

    def collect(_discovery, _options, wheel_directory, _source_copy):
        wheel_directory.mkdir()
        copy2(wheel, wheel_directory / wheel.name)

    monkeypatch.setattr('portablepy.builder.collect_wheels', collect)
    output = build_bundle(
        BuildOptions(source, ('python', '-m', 'demo_app'), tmp_path / 'generated.zip')
    )
    destination = tmp_path / 'generated'
    destination.mkdir()
    assert 'installed' in launch(extract(output, destination))


def test_project_example_bundle_contains_only_example_and_parent_package(
    tmp_path, wheel_factory, monkeypatch
):
    wheel = wheel_factory()
    source = tmp_path / 'project'
    source.mkdir()
    (source / 'pyproject.toml').write_text('[project]\nname="demo-app"\nversion="1.0"\n')
    library = source / 'src/demo_app'
    library.mkdir(parents=True)
    (library / '__init__.py').write_text('import build_only_dependency\n')
    example = source / 'examples/bot'
    example.mkdir(parents=True)
    (source / 'examples/__init__.py').write_text('"""Examples."""\n')
    (example / '__init__.py').write_text('"""Bot."""\n')
    (example / '__main__.py').write_text(
        'from demo_app import VALUE\nfrom pathlib import Path\nprint(VALUE, Path(__file__).with_name("words.json").read_text())\n'
    )
    (example / 'words.json').write_text('resource preserved')
    other = source / 'examples/other'
    other.mkdir()
    (other / '__main__.py').write_text('import unrelated_dependency\n')
    (source / 'examples/old-bundle.zip').write_bytes(b'old archive')
    (source / 'test.py').write_text('import missing_dev_tool\n')

    def collect(_discovery, _options, wheel_directory, source_copy):
        # The build backend still gets the full project; the app payload must not.
        assert (source_copy / 'src/demo_app/__init__.py').is_file()
        wheel_directory.mkdir()
        copy2(wheel, wheel_directory / wheel.name)

    monkeypatch.setattr('portablepy.builder.collect_wheels', collect)
    output = build_bundle(
        BuildOptions(
            source,
            ('python', '-m', 'examples.bot'),
            tmp_path / 'example.zip',
            compile_mode='all',
            strip_source=True,
        )
    )
    manifest = verify_bundle(output)
    prefix = manifest['app_directory'] + '/'
    assert {name.removeprefix(prefix) for name in manifest['files'] if name.startswith(prefix)} == {
        'examples/__init__.pyc',
        'examples/bot/__init__.pyc',
        'examples/bot/__main__.pyc',
        'examples/bot/words.json',
    }
    destination = tmp_path / 'example'
    destination.mkdir()
    assert 'installed resource preserved' in launch(extract(output, destination))


def test_entry_point_build_finds_installed_wheel_without_requirements_or_links(
    tmp_path, wheel_factory
):
    wheel = wheel_factory()
    environment = tmp_path / 'build-environment'
    run([executable, '-m', 'venv', str(environment)], check=True)
    python = environment / (
        'Scripts/python.exe' if (environment / 'Scripts').exists() else 'bin/python'
    )
    run([str(python), '-m', 'pip', 'install', '--no-index', str(wheel)], check=True)
    source = tmp_path / 'application'
    source.mkdir()
    (source / 'main.py').write_text('from demo_app import VALUE\nprint(VALUE)\n')
    (source / 'unrelated_test.py').write_text('import nonexistent_test_dependency\n')
    output = build_bundle(
        BuildOptions(
            source, ('python', 'main.py'), tmp_path / 'automatic.zip', python, no_index=True
        )
    )
    manifest = verify_bundle(output)
    assert len([name for name in manifest['files'] if name.endswith('.whl')]) == 1
    destination = tmp_path / 'automatic'
    destination.mkdir()
    assert 'installed' in launch(extract(output, destination))


def test_application_directory_hash_covers_paths_and_resources(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'main.py').write_text('print("hello")\n')
    resource = source / 'resource.txt'
    resource.write_text('initial')
    # Other integration tests exercise offline setup; these builds compare application snapshots.
    monkeypatch.setattr('portablepy.builder.run', lambda *_args, **_kwargs: None)

    def build(name):
        output = build_bundle(BuildOptions(source, ('python', 'main.py'), tmp_path / name))
        return verify_bundle(output)

    first = build('first.zip')
    resource.touch()
    second = build('different-name.zip')
    assert first['app_directory'] == second['app_directory']
    assert len(first['app_directory']) == 64
    assert first['app_directory'] + '/resource.txt' in first['files']
    resource.write_text('changed')
    third = build('changed.zip')
    assert third['app_directory'] != first['app_directory']
    renamed = source / 'renamed.txt'
    assert renamed.resolve().is_relative_to(source.resolve())
    resource.rename(renamed)
    fourth = build('renamed.zip')
    assert fourth['app_directory'] != third['app_directory']
    destination = tmp_path / 'extracted'
    destination.mkdir()
    root = extract(tmp_path / 'renamed.zip', destination)
    (root / fourth['app_directory'] / 'unexpected.py').write_text('print("unlisted")\n')
    with raises(ValueError, match='Application files do not match'):
        verify_bundle(root)
