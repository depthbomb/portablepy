from json import loads
from subprocess import run
from sys import executable
from portablepy.verify import verify_bundle


def test_cli_help_and_invalid_compilation_options(tmp_path):
    help_result = run(
        [executable, '-m', 'portablepy', 'build', '--help'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert '--strip-source' in help_result.stdout
    result = run(
        [
            executable,
            '-m',
            'portablepy',
            'build',
            str(tmp_path),
            '--run',
            'python app.py',
            '--output',
            str(tmp_path / 'app.zip'),
            '--strip-source',
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert '--strip-source requires' in result.stderr


def test_cli_build_defaults_output_to_current_directory(tmp_path):
    source = tmp_path / 'application'
    source.mkdir()
    (source / 'main.py').write_text('print("started")\n')
    command = [
        executable,
        '-m',
        'portablepy',
        'build',
        str(source),
        '--run',
        'python main.py',
        '--compile',
        'all',
        '--strip-source',
    ]
    result = run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    archives = [
        path for path in tmp_path.glob('application-auto-*') if not path.name.endswith('.sha256')
    ]
    assert len(archives) == 1
    archive = archives[0]
    assert str(archive) in result.stdout
    manifest = verify_bundle(archive)
    assert manifest['app_directory'] + '/main.pyc' in manifest['files']
    before = archive.read_bytes()
    repeated = run(command, cwd=tmp_path, capture_output=True, text=True)
    assert repeated.returncode == 1 and 'already exists' in repeated.stderr
    assert archive.read_bytes() == before


def test_cli_profile_build_and_inspection(tmp_path):
    source = tmp_path / 'app'
    source.mkdir()
    (source / 'main.py').write_text('print("profile app")')
    (tmp_path / 'pyproject.toml').write_text(
        "[tool.portablepy]\nsource = 'app'\nrun = 'python main.py'\noutput = 'profile.zip'\n"
        "[tool.portablepy.profiles.release]\ncompile = 'all'\nstrip-source = true\nno-index = true\n"
    )
    result = run(
        [executable, '-m', 'portablepy', 'inspect', '--profile', 'release', '--resolve'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = loads(result.stdout)
    assert report['profile'] == 'release' and report['size']['includes_wheels']
    assert not (tmp_path / 'profile.zip').exists()
    built = run(
        [executable, '-m', 'portablepy', 'build', '--profile', 'release', '--keep-source'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    manifest = verify_bundle(tmp_path / 'profile.zip')
    assert not manifest['strip_source'] and manifest['compile'] == 'all'
    assert manifest['app_directory'] + '/main.py' in manifest['files']
