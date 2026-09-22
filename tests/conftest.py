from csv import writer
from io import StringIO
from pytest import fixture
from zipfile import ZipFile
from portablepy.wheels import digest


@fixture
def wheel_factory(tmp_path):
    def make(name='demo_app', *, requires=(), extra_files=None):
        info = f'{name}-1.0.dist-info'
        files = {
            f'{name}/__init__.py': b"VALUE = 'installed'\n",
            f'{name}/__main__.py': b'from .cli import main\nraise SystemExit(main())\n',
            f'{name}/cli.py': b"from sys import argv\ndef main():\n    print('installed', *argv[1:])\n    return 0\n",
            f'{info}/METADATA': (
                'Metadata-Version: 2.4\nName: '
                + name.replace('_', '-')
                + '\nVersion: 1.0\n'
                + ''.join(f'Requires-Dist: {item}\n' for item in requires)
                + '\n'
            ).encode(),
            f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n',
            f'{info}/entry_points.txt': f'[console_scripts]\ndemo-command = {name}.cli:main\n'.encode(),
            f'{info}/licenses/LICENSE': b'Test fixture license\n',
        }
        files.update(extra_files or {})
        record = StringIO(newline='')
        rows = writer(record, lineterminator='\n')
        for path, data in files.items():
            rows.writerow((path, f'sha256={digest(data)}', len(data)))
        rows.writerow((f'{info}/RECORD', '', ''))
        files[f'{info}/RECORD'] = record.getvalue().encode()
        wheel = tmp_path / f'{name}-1.0-py3-none-any.whl'
        with ZipFile(wheel, 'w') as archive:
            for path, data in files.items():
                archive.writestr(path, data)
        return wheel

    return make
