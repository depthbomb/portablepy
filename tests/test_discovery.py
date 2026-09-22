from pathlib import Path
from pytest import raises
from sys import executable
from portablepy.models import BuildOptions
from portablepy.discovery import discover, find_python, scan_imports


def test_scan_follows_local_modules_and_reports_ambiguous_names(tmp_path):
    (tmp_path / 'main.py').write_text('import json\nimport helper\nimport mystery\n')
    (tmp_path / 'helper.py').write_text('from imported_name import thing\n')
    runtime = {
        'stdlib': ['json'],
        'distributions': {'imported_name': ['real-distribution']},
        'versions': {'real-distribution': '2.0'},
    }
    requirements, unknown = scan_imports(tmp_path / 'main.py', runtime)
    assert requirements == ['real-distribution==2.0']
    assert unknown == ['mystery']


def test_project_metadata_takes_precedence_over_dev_imports(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="sample"\nversion="1.0"\n')
    (tmp_path / 'test.py').write_text('import nonexistent_dev_tool\n')
    result = discover(BuildOptions(tmp_path, (), tmp_path / 'out.zip'))
    assert result.mode == 'project' and not result.unresolved


def test_requirements_file_takes_precedence_over_scanning(tmp_path):
    (tmp_path / 'main.py').write_text('import plugin\n')
    (tmp_path / 'requirements.txt').write_text('plugin-dist==1.0\n')
    result = discover(BuildOptions(tmp_path, (), tmp_path / 'out.zip'))
    assert result.requirement_files == [tmp_path / 'requirements.txt']
    assert not result.unresolved


def test_explicit_interpreter_is_not_resolved_out_of_venv(tmp_path):
    python = tmp_path / 'python'
    try:
        python.symlink_to(executable)
    except OSError:
        python.write_text('placeholder')
    assert find_python(tmp_path, python) == python
    with raises(ValueError, match='does not exist'):
        find_python(tmp_path, Path('missing-python'))


def test_launch_package_infers_discovered_commands_without_scanning_tests(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="framework"\nversion="1.0"\n')
    library = tmp_path / 'src/framework'
    library.mkdir(parents=True)
    (library / '__init__.py').write_text('import optional_image_dependency\n')
    example = tmp_path / 'examples/bot'
    example.mkdir(parents=True)
    (example / '__main__.py').write_text('import command_framework\n')
    (example / 'commands.py').write_text('import framework\nimport another_dependency\n')
    (tmp_path / 'test.py').write_text('import missing_dev_tool\n')
    monkeypatch.setattr(
        'portablepy.discovery.probe',
        lambda _python: {
            'stdlib': [],
            'distributions': {'command_framework': ['cli'], 'another_dependency': ['extra']},
            'versions': {'cli': '1.0', 'extra': '2.0'},
        },
    )
    result = discover(
        BuildOptions(tmp_path, ('python', '-m', 'examples.bot'), tmp_path / 'out.zip')
    )
    assert result.requirements == ['cli==1.0', 'extra==2.0']
    assert not result.unresolved


def test_imported_editable_dependency_uses_its_source(tmp_path):
    application = tmp_path / 'app.py'
    application.write_text('import local_package\n')
    checkout = tmp_path / 'other-project'
    checkout.mkdir()
    requirements, unresolved = scan_imports(
        application,
        {
            'stdlib': [],
            'distributions': {'local_package': ['Local.Package']},
            'versions': {'Local.Package': '1.0'},
            'origins': {'local-package': str(checkout)},
        },
    )
    assert requirements == [str(checkout)]
    assert not unresolved


def test_nested_script_resolves_its_sibling_imports(tmp_path):
    scripts = tmp_path / 'tools'
    scripts.mkdir()
    entry = scripts / 'main.py'
    entry.write_text('import helper\n')
    (scripts / 'helper.py').write_text('import json\n')
    requirements, unresolved = scan_imports(
        tmp_path,
        {'stdlib': ['json'], 'distributions': {}, 'versions': {}},
        seeds=(entry,),
    )
    assert not requirements and not unresolved


def test_standard_library_module_needs_no_distribution(tmp_path):
    result = discover(BuildOptions(tmp_path, ('python', '-m', 'http.server'), tmp_path / 'out.zip'))
    assert not result.requirements and not result.unresolved


def test_console_entry_point_selects_distribution_without_scanning_unrelated_files(
    tmp_path, monkeypatch
):
    (tmp_path / 'unused.py').write_text('import nonexistent\n')
    monkeypatch.setattr(
        'portablepy.discovery.probe',
        lambda _python: {
            'stdlib': [],
            'distributions': {},
            'versions': {'console-package': '3.0'},
            'commands': {'example-cli': ['console-package']},
        },
    )
    result = discover(BuildOptions(tmp_path, ('example-cli', '--help'), tmp_path / 'out.zip'))
    assert result.requirements == ['console-package==3.0']
    assert not result.unresolved
