from pathlib import Path
from pytest import raises
from portablepy.cli import build
from portablepy.config import resolve_options


CONFIG = """
[tool.portablepy]
source = 'app'
run = 'python main.py'
output = 'release/app.zip'
include = ['defaults.json=data/state.json']
find-links = ['wheels']
requirement = ['demo>=1']
[tool.portablepy.profiles.release]
compile = 'all'
strip-source = true
no-index = true
replace = true
requirement = ['demo==1']
"""


def test_config_profiles_paths_and_cli_precedence(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    config = project / 'pyproject.toml'
    config.write_text(CONFIG)
    monkeypatch.chdir(tmp_path)
    options = resolve_options(config=config, profile='release')
    assert options.source == project / 'app'
    assert options.output == project / 'release/app.zip'
    assert options.includes == (str(project / 'defaults.json') + '=data/state.json',)
    assert options.find_links == (str(project / 'wheels'),)
    assert options.requirements == ('demo==1',)
    assert options.compile_mode == 'all' and options.strip_source and options.replace
    captured = []
    archive = tmp_path / 'output.zip'
    archive.write_bytes(b'archive')

    def fake_build(value):
        captured.append(value)
        return archive

    monkeypatch.setattr('portablepy.cli.build_bundle', fake_build)
    build(
        Path('different'),
        config=config,
        profile='release',
        keep_source=True,
        use_index=True,
        no_replace=True,
        requirement=['other==2'],
        output=Path('output.zip'),
    )
    actual = captured[0]
    assert actual.source == Path('different')
    assert actual.output == Path('output.zip')
    assert actual.requirements == ('other==2',)
    assert not actual.strip_source and not actual.no_index and not actual.replace


def test_implicit_config_search_and_unknown_profile(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text(CONFIG)
    child = tmp_path / 'app'
    child.mkdir()
    monkeypatch.chdir(child)
    assert resolve_options(profile='release').source == child
    with raises(ValueError, match='available profiles: release'):
        resolve_options(profile='missing')


def test_invalid_config_and_conflicting_flags(tmp_path):
    config = tmp_path / 'pyproject.toml'
    for contents, message in (
        ("replace = 'yes'", 'Invalid'),
        ('typo = true', 'Unknown'),
        ("compile = 'fast'", 'must be none'),
    ):
        config.write_text('[tool.portablepy]\n' + contents)
        with raises(ValueError, match=message):
            resolve_options(config=config)
    with raises(ValueError, match='Choose only one'):
        build(tmp_path, replace=True, no_replace=True)
