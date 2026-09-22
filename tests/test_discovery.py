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
