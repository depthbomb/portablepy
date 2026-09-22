from portablepy.models import BuildOptions
from portablepy.inspection import inspection_report


def test_inspect_explains_imports_resources_and_sizes(tmp_path):
    (tmp_path / 'main.py').write_text('import helper\nimport argly\n')
    (tmp_path / 'helper.py').write_text('VALUE = 1\n')
    (tmp_path / 'data.json').write_text('{}')
    (tmp_path / 'unrelated.py').write_text('import nonexistent_package\n')
    report = inspection_report(BuildOptions(tmp_path, ('python', 'main.py')))
    entries = {entry['path']: entry for entry in report['files']}
    assert set(entries) == {'main.py', 'helper.py', 'data.json'}
    assert 'Import in main.py:1' in entries['helper.py']['reasons']
    assert 'Resource' in entries['data.json']['reasons'][0]
    assert report['size']['payload_bytes'] == sum(entry['bytes'] for entry in entries.values())
    assert not report['size']['includes_wheels']
    assert 'argly: Import in main.py:2' in report['dependency_inputs'][0]['reason']
    assert not report['unresolved_imports']


def test_resolved_inspection_reports_transitive_wheels_and_origins(tmp_path, wheel_factory):
    wheel_factory('demo_dependency')
    wheel = wheel_factory(requires=['demo-dependency==1.0'])
    report = inspection_report(
        BuildOptions(
            wheel, ('python', '-m', 'demo_app'), no_index=True, find_links=(str(tmp_path),)
        ),
        resolve=True,
    )
    inventory = {entry['name']: entry for entry in report['wheels']}
    assert set(inventory) == {'demo-app', 'demo-dependency'}
    assert inventory['demo-app']['origin'] == {'kind': 'local wheel', 'path': str(wheel)}
    assert inventory['demo-dependency']['declared_by'] == [
        {'name': 'demo-app', 'requirement': 'demo-dependency==1.0'}
    ]
    assert report['size']['includes_wheels']
    assert report['size']['payload_bytes'] == sum(entry['bytes'] for entry in inventory.values())
    assert not (tmp_path / '.venv').exists()
