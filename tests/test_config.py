from pathlib import Path
from pytest import mark, raises
from portablepy.config import resolve_options


CONFIG = """
source = 'app'
run = 'python main.py'
output = 'release/app.zip'
python = '.venv/Scripts/python.exe'
include = ['defaults.json=data/state.json']
find-links = ['wheels', 'https://example.com/wheels']
requirement = ['demo>=1']
requirements = ['requirements.txt']
extra = ['cli']
exclude = ['*.log']
profile = 'release'
python-version = '3.14.8'
[profiles.release]
compile = 'all'
strip-source = true
no-index = true
replace = true
resolve = true
requirement = ['demo==1']
"""


def test_config_profiles_and_paths_are_relative_to_file(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    config = project / 'portablepy.toml'
    config.write_text(CONFIG)
    monkeypatch.chdir(tmp_path)
    options = resolve_options(config)
    assert options.source == project / 'app'
    assert options.output == project / 'release/app.zip'
    assert options.python == project / '.venv/Scripts/python.exe'
    assert options.includes == (str(project / 'defaults.json') + '=data/state.json',)
    assert options.find_links == (str(project / 'wheels'), 'https://example.com/wheels')
    assert options.requirements == ('demo==1',)
    assert options.requirement_files == (project / 'requirements.txt',)
    assert options.extras == ('cli',) and options.excludes == ('*.log',)
    assert options.compile_mode == 'all' and options.strip_source and options.replace
    assert options.no_index and options.resolve
    assert options.profile == 'release' and options.config == config
    assert options.python_version == '3.14.8'
    assert Path.cwd() == tmp_path


def test_nearest_config_search_ignores_pyproject(tmp_path, monkeypatch):
    (tmp_path / 'portablepy.toml').write_text(CONFIG)
    child = tmp_path / 'app'
    child.mkdir()
    (child / 'pyproject.toml').write_text('[project]\nname = "app"\n')
    monkeypatch.chdir(child)
    assert resolve_options().source == child
    (child / 'portablepy.toml').write_text("run = 'python child.py'\n")
    options = resolve_options()
    assert options.config == child / 'portablepy.toml'
    assert options.source == child and options.command == ('python', 'child.py')
    assert options.output is None and options.profile is None
    assert not options.resolve and not options.replace


def test_missing_config_does_not_fall_back_to_pyproject(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text("[tool.portablepy]\nrun = 'python main.py'\n")
    monkeypatch.chdir(tmp_path)
    with raises(ValueError, match='No portablepy.toml found'):
        resolve_options()
    with raises(ValueError, match='not a file'):
        resolve_options(tmp_path)
    with raises(ValueError, match='Configuration file does not exist'):
        resolve_options(tmp_path / 'missing.toml')


@mark.parametrize(
    'settings,message',
    [
        ("replace = 'yes'", 'replace must be a boolean'),
        ('resolve = 1', 'resolve must be a boolean'),
        ('typo = true', 'unknown settings: typo'),
        ("compile = 'fast'", 'compile must be none'),
        ("requirements = 'requirements.txt'", 'requirements must be an array'),
        ("requirement = ['']", 'requirement must be an array'),
        ("source = '  '", 'source must be a nonempty string'),
        ("include = ['bad']", 'include uses SOURCE=data/DESTINATION'),
        ("include = ['=data/settings.json']", 'include uses SOURCE=data/DESTINATION'),
        ('strip-source = true', 'strip-source = true requires compile'),
        ('profiles = []', 'profiles must be a TOML table'),
        ('profile = true', 'profile must be a nonempty string'),
        ("profile = 'missing'", r'available profiles: \(none\)'),
        ('[profiles.release]\ntypo = true', 'unknown settings: typo'),
        ('[profiles]\nrelease = false', 'settings must be a TOML table'),
        ('[tool.portablepy]', 'unknown settings: tool'),
    ],
)
def test_invalid_settings_have_actionable_errors(tmp_path, settings, message):
    config = tmp_path / 'portablepy.toml'
    config.write_text("run = 'python main.py'\n" + settings)
    with raises(ValueError, match=message) as error:
        resolve_options(config)
    assert str(config) in str(error.value)


@mark.parametrize('contents', ['', "run = ''", 'run = \'""\'', "run = '   '"])
def test_missing_or_empty_launch_command(tmp_path, contents):
    config = tmp_path / 'portablepy.toml'
    config.write_text(contents)
    with raises(ValueError, match='run'):
        resolve_options(config)


def test_invalid_toml_and_command_quoting_name_the_config(tmp_path):
    config = tmp_path / 'portablepy.toml'
    config.write_text('run = [')
    with raises(ValueError, match='Invalid TOML in'):
        resolve_options(config)
    config.write_text("run = 'python \"main.py'")
    with raises(ValueError, match='invalid run command'):
        resolve_options(config)


def test_profile_can_clear_lists_and_disable_settings(tmp_path):
    config = tmp_path / 'portablepy.toml'
    config.write_text(
        CONFIG.replace("requirement = ['demo==1']", 'requirement = []').replace(
            'replace = true', 'replace = false'
        )
    )
    options = resolve_options(config)
    assert options.requirements == () and not options.replace


def test_local_package_requirement_is_relative_to_config(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    package = project / 'local-package'
    package.mkdir()
    config = project / 'custom.toml'
    config.write_text("run = 'python main.py'\nrequirement = ['./local-package', 'requests>=2']\n")
    monkeypatch.chdir(tmp_path)
    assert resolve_options(config).requirements == (str(package), 'requests>=2')
