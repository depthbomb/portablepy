from json import loads
from pathlib import Path
from pytest import mark
from subprocess import run
from sys import executable
from portablepy.verify import verify_bundle


def invoke(*arguments, cwd=None):
    return run(
        [executable, '-m', 'portablepy', *arguments], cwd=cwd, capture_output=True, text=True
    )


@mark.parametrize('command', ['build', 'inspect'])
def test_cli_only_accepts_config_and_help(command, tmp_path):
    help_result = invoke(command, '--help')
    assert help_result.returncode == 0
    assert '[CONFIG]' in help_result.stdout and 'portablepy.toml' in help_result.stdout
    assert '--run' not in help_result.stdout and '--profile' not in help_result.stdout
    result = invoke(command, '--run', 'python main.py', cwd=tmp_path)
    assert result.returncode != 0
    config = tmp_path / 'portablepy.toml'
    config.write_text("run = 'python main.py'\nstrip-source = true\n")
    result = invoke(command, cwd=tmp_path)
    assert result.returncode == 1
    assert 'strip-source = true requires' in result.stderr
    assert 'Traceback' not in result.stderr


def test_generated_help_is_current_and_loads_without_handlers():
    project = Path(__file__).resolve().parents[1]
    checked = run(
        [
            executable,
            '-m',
            'argly',
            'gen',
            '--package',
            'portablepy.commands',
            '--name',
            'portablepy',
            '--output',
            'src/portablepy/generated.py',
            '--check',
        ],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr
    help_result = run(
        [
            executable,
            '-c',
            'import sys; from portablepy.cli import main; '
            "sys.argv = ['portablepy', 'build', '--help']; "
            "assert main() == 0; assert 'portablepy.builder' not in sys.modules",
        ],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr


def test_cli_build_defaults_output_to_config_directory(tmp_path):
    project = tmp_path / 'project'
    source = project / 'application'
    source.mkdir(parents=True)
    (source / 'main.py').write_text('print("started")\n')
    config = project / 'portablepy.toml'
    config.write_text(
        "source = 'application'\nrun = 'python main.py'\ncompile = 'all'\nstrip-source = true\n"
    )
    result = invoke('build', str(config), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    archives = [
        path for path in project.glob('application-auto-*') if not path.name.endswith('.sha256')
    ]
    assert len(archives) == 1
    archive = archives[0]
    assert str(archive) in result.stdout
    manifest = verify_bundle(archive)
    assert manifest['app_directory'] + '/main.pyc' in manifest['files']
    before = archive.read_bytes()
    repeated = invoke('build', str(config), cwd=tmp_path)
    assert repeated.returncode == 1 and 'already exists' in repeated.stderr
    assert archive.read_bytes() == before
    checked = invoke('verify', str(archive))
    assert checked.returncode == 0 and 'Checksums passed' in checked.stdout


def test_cli_profile_build_and_resolved_inspection(tmp_path):
    source = tmp_path / 'app'
    source.mkdir()
    (source / 'main.py').write_text('print("profile app")')
    (tmp_path / 'portablepy.toml').write_text(
        "source = 'app'\nrun = 'python main.py'\noutput = 'profile.zip'\nprofile = 'release'\n"
        "[profiles.release]\ncompile = 'all'\nstrip-source = false\nno-index = true\nresolve = true\n"
    )
    result = invoke('inspect', cwd=source)
    assert result.returncode == 0, result.stderr
    report = loads(result.stdout)
    assert report['profile'] == 'release' and report['size']['includes_wheels']
    assert report['output'] == str(tmp_path / 'profile.zip')
    assert not (tmp_path / 'profile.zip').exists()
    built = invoke('build', cwd=source)
    assert built.returncode == 0, built.stdout + built.stderr
    manifest = verify_bundle(tmp_path / 'profile.zip')
    assert not manifest['strip_source'] and manifest['compile'] == 'all'
    assert manifest['app_directory'] + '/main.py' in manifest['files']


def test_cli_missing_config_explains_how_to_start(tmp_path):
    result = invoke('build', cwd=tmp_path)
    assert result.returncode == 1
    assert "run = 'python main.py'" in result.stderr
    assert 'Traceback' not in result.stderr
