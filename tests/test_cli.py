from subprocess import run
from sys import executable


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
