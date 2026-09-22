from portablepy.discovery import discover
from portablepy.models import BuildOptions


def write(root, name, content=''):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_nested_entry_point_preserves_imports_and_resources_without_sibling_apps(tmp_path):
    write(tmp_path, 'examples/__init__.py', '"""Application examples."""\n')
    write(tmp_path, 'examples/bot/__init__.py', '"""Bot package."""\n')
    write(tmp_path, 'examples/bot/__main__.py', 'from . import commands\n')
    write(tmp_path, 'examples/bot/commands.py', 'from ..shared import value\nimport json\n')
    write(tmp_path, 'examples/bot/data/words.json', '{}')
    write(tmp_path, 'examples/shared.py', 'value = 1\n')
    write(tmp_path, 'examples/other/__main__.py', 'import missing_other_app_dependency\n')
    write(tmp_path, 'examples/old-bundle.zip', 'unrelated archive')
    write(tmp_path, 'tests/test_app.py', 'import missing_dev_dependency\n')
    write(tmp_path, 'README.md', 'Unrelated repository documentation')
    found = discover(BuildOptions(tmp_path, ('python', '-m', 'examples.bot')))
    assert not found.requirements and not found.unresolved
    assert {path.relative_to(tmp_path).as_posix() for path in found.application_files} == {
        'examples/__init__.py',
        'examples/bot/__init__.py',
        'examples/bot/__main__.py',
        'examples/bot/commands.py',
        'examples/bot/data/words.json',
        'examples/shared.py',
    }


def test_explicit_requirements_still_select_entry_point_files_and_honor_exclusions(tmp_path):
    write(tmp_path, 'examples/__init__.py', '"""Examples."""\n')
    write(tmp_path, 'examples/bot/__main__.py', 'import dynamically_supplied_plugin\n')
    write(tmp_path, 'examples/bot/words.json', '{}')
    write(tmp_path, 'examples/other/__main__.py', 'import unrelated\n')
    found = discover(
        BuildOptions(
            tmp_path,
            ('python', '-m', 'examples.bot'),
            requirements=('plugin-package',),
            excludes=('examples/bot/words.json',),
        )
    )
    assert found.requirements == ['plugin-package'] and not found.unresolved
    assert {path.relative_to(tmp_path).as_posix() for path in found.application_files} == {
        'examples/__init__.py',
        'examples/bot/__main__.py',
    }


def test_single_script_includes_imported_helpers_and_adjacent_resources(tmp_path):
    write(tmp_path, 'main.py', 'import helper\n')
    write(tmp_path, 'helper.py', 'import json\n')
    write(tmp_path, 'words.json', '{}')
    write(tmp_path, 'unrelated.py', 'import missing_dependency\n')
    found = discover(BuildOptions(tmp_path / 'main.py', ('python', 'main.py')))
    assert not found.requirements and not found.unresolved
    assert {path.name for path in found.application_files} == {'main.py', 'helper.py', 'words.json'}
