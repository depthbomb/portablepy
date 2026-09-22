from pathlib import Path
from pytest import mark, raises
from portablepy.files import data_files, selected_files
from portablepy.entrypoints import command_target
from portablepy.launcher import application_command


@mark.parametrize(
    'destinations',
    [
        ('data/a', 'data/a'),
        ('data/a', 'data/a/b'),
        ('data/a/b', 'data/a'),
    ],
)
def test_data_overlaps_in_both_orders(tmp_path, destinations):
    (tmp_path / 'seed').write_text('seed')
    with raises(ValueError, match='overlap'):
        data_files(tuple(f'seed={name}' for name in destinations), tmp_path)


def test_data_siblings_and_similar_prefixes_are_allowed(tmp_path):
    (tmp_path / 'seed').write_text('seed')
    destinations = ('data/a/b', 'data/a/c', 'data/ab', 'data/abc/d')
    result = data_files(tuple(f'seed={name}' for name in destinations), tmp_path)
    assert tuple(map(str, result)) == destinations


def test_source_walk_reports_unreadable_directories(tmp_path, monkeypatch):
    def denied(self, *, on_error=None, **kwargs):
        if on_error:
            on_error(PermissionError('directory inaccessible'))
        return iter(())

    monkeypatch.setattr(Path, 'walk', denied)
    with raises(PermissionError, match='inaccessible'):
        list(selected_files(tmp_path))


@mark.parametrize(
    'arguments,expected',
    [
        (('main.py', 'input.py'), ('main.pyc', 'input.py')),
        (('-W', 'input.py', 'main.py', 'input.py'), ('-W', 'input.py', 'main.pyc', 'input.py')),
        (('-m', 'app', 'input.py'), ('-m', 'app', 'input.py')),
        (('-mapp', 'input.py'), ('-mapp', 'input.py')),
        (('-c', 'pass', 'input.py'), ('-c', 'pass', 'input.py')),
        (('-', 'input.py'), ('-', 'input.py')),
        (('--', 'main.py', 'input.py'), ('--', 'main.pyc', 'input.py')),
        (
            ('--check-hash-based-pycs', 'always', 'main.py'),
            ('--check-hash-based-pycs', 'always', 'main.pyc'),
        ),
    ],
)
def test_stripping_changes_only_the_script_argument(tmp_path, arguments, expected):
    app = tmp_path / 'app'
    app.mkdir()
    for name in ('main.pyc', 'input.pyc'):
        (app / name).write_bytes(b'bytecode')
    python = tmp_path / 'python'
    manifest = {'command': ['python', *arguments], 'python_command': True, 'strip_source': True}
    result = application_command(tmp_path, manifest, python, ['forwarded.py'])
    assert result == [str(python), *expected, 'forwarded.py']


@mark.parametrize(
    'arguments,expected',
    [
        (('--check-hash-based-pycs', 'always', 'main.py'), ('script', 'main.py')),
        (('-mapp',), ('module', 'app')),
        (('-cpass', 'input.py'), ('', '')),
        (('-', 'input.py'), ('', '')),
        (('--', '-script.py'), ('script', '-script.py')),
    ],
)
def test_python_launch_target_options(arguments, expected):
    assert command_target(('python', *arguments)) == expected
