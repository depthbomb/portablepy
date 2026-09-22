from pytest import mark
from pathlib import Path
from portablepy.models import Discovery
from portablepy.output import default_output


@mark.parametrize(
    'platform,machine,bits,free_threaded,suffix',
    [
        ('win32', 'AMD64', 64, False, 'windows-x64-py314.zip'),
        ('linux', 'x86_64', 64, False, 'linux-x64-py314.tar.gz'),
        ('darwin', 'arm64', 64, False, 'macos-arm64-py314.tar.gz'),
        ('linux', 'aarch64', 64, True, 'linux-arm64-py314t.tar.gz'),
        ('win32', 'AMD64', 32, False, 'windows-x86-py314.zip'),
    ],
)
def test_default_output_uses_project_command_and_target_runtime(
    tmp_path, monkeypatch, platform, machine, bits, free_threaded, suffix
):
    source = tmp_path / 'different-checkout-name'
    source.mkdir()
    (source / 'pyproject.toml').write_text('[project]\nname="skribblpy"\n')
    destination = tmp_path / 'current-directory'
    destination.mkdir()
    monkeypatch.chdir(destination)
    found = Discovery(
        source,
        Path('python'),
        {
            'platform': platform,
            'machine': machine,
            'bits': bits,
            'version': [3, 14],
            'free_threaded': free_threaded,
        },
        'project',
    )
    assert default_output(found, ('python', '-X', 'dev', '-m', 'examples.word_guesser', 'run')) == (
        destination / ('skribblpy-word-guesser-auto-' + suffix)
    )


@mark.parametrize(
    'source,mode,command,expected',
    [
        ('hello.py', 'script', ('python', 'hello.py'), 'hello'),
        ('my_app-1.0-py3-none-any.whl', 'wheel', ('my-app',), 'my-app'),
        (
            'skribblpy_word_guesser-1.0-py3-none-any.whl',
            'wheel',
            ('python', '-m', 'examples.word_guesser'),
            'skribblpy-word-guesser',
        ),
        ('My App!', 'directory', ('python', 'main.py'), 'my-app'),
    ],
)
def test_default_output_avoids_duplicate_names(tmp_path, source, mode, command, expected):
    found = Discovery(
        tmp_path / source,
        Path('python'),
        {
            'platform': 'win32',
            'machine': 'amd64',
            'bits': 64,
            'version': [3, 14],
        },
        mode,
    )
    assert default_output(found, command).name == expected + '-auto-windows-x64-py314.zip'
