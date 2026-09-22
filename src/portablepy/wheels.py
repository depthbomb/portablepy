"""Wheel resolution, integrity checking, and bytecode repacking."""

from io import StringIO
from pathlib import Path
from subprocess import run
from re import sub, fullmatch
from csv import reader, writer
from hashlib import new, sha256
from base64 import urlsafe_b64encode
from email.parser import BytesParser
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
from portablepy.files import portable_path
from portablepy.bytecode import compile_tree


def digest(data: bytes) -> str:
    return urlsafe_b64encode(sha256(data).digest()).rstrip(b'=').decode('ascii')


def wheel_metadata(path: Path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError(f'Duplicate wheel entries: {path.name}')
        for name in names:
            portable_path(name.rstrip('/'))
        metadata_files = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata_files) != 1:
            raise ValueError(f'Expected one wheel metadata file: {path.name}')
        prefix = metadata_files[0].rsplit('/', 1)[0]
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if not metadata['Name'] or not metadata['Version']:
            raise ValueError(f'Wheel has no name/version: {path.name}')
        if not fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', metadata['Name']) or not fullmatch(
            r'[A-Za-z0-9][A-Za-z0-9.!+_-]*', metadata['Version']
        ):
            raise ValueError(f'Invalid wheel name/version: {path.name}')
        for requirement in metadata.get_all('Requires-Dist', []):
            if '@' in requirement.split(';', 1)[0]:
                raise ValueError(
                    f'Direct URL dependency cannot be installed offline: {requirement}'
                )
        rows = list(reader(StringIO(archive.read(f'{prefix}/RECORD').decode('utf-8'))))
        recorded = set()
        for row in rows:
            if len(row) != 3 or row[0] in recorded:
                raise ValueError(f'Invalid wheel RECORD: {path.name}')
            name, checksum, size = row
            portable_path(name)
            recorded.add(name)
            data = archive.read(name)
            if name == f'{prefix}/RECORD':
                continue
            if not checksum and name.endswith(('.pyc', '/RECORD.jws', '/RECORD.p7s')):
                continue
            algorithm, separator, expected = checksum.partition('=')
            if not separator or algorithm not in ('sha256', 'sha384', 'sha512'):
                raise ValueError(f'Unsupported wheel digest: {path.name}: {name}')
            actual = urlsafe_b64encode(new(algorithm, data).digest()).rstrip(b'=').decode('ascii')
            if actual != expected or size != str(len(data)):
                raise ValueError(f'Wheel RECORD mismatch: {path.name}: {name}')
        unrecorded = {name for name in names if not name.endswith('/')} - recorded
        unrecorded -= {f'{prefix}/RECORD.jws', f'{prefix}/RECORD.p7s'}
        if unrecorded:
            raise ValueError(f'Unrecorded wheel files: {sorted(unrecorded)}')
    return metadata


def repack_bytecode(path: Path, python: Path, runtime: dict, *, strip=False) -> Path:
    wheel_metadata(path)
    fields = path.stem.split('-')
    if len(fields) not in (5, 6):
        raise ValueError(f'Invalid wheel filename: {path.name}')
    platform = fields[-1]
    python_tag = 'cp' + ''.join(map(str, runtime['version']))
    abi = python_tag + ('t' if runtime['free_threaded'] else '') if platform != 'any' else 'none'
    tag = f'{python_tag}-{abi}-{platform}'
    destination = path.with_name(f'{fields[0]}-{fields[1]}-1portable-{tag}.whl')
    with TemporaryDirectory(prefix='portablepy-wheel-') as temporary:
        root = Path(temporary)
        with ZipFile(path) as archive:
            archive.extractall(root)
            modes = {item.filename: item.external_attr for item in archive.infolist()}
        compile_tree(root, python, strip=strip)
        metadata = next(root.glob('*.dist-info'))
        wheel_file = metadata / 'WHEEL'
        lines = [
            line
            for line in wheel_file.read_text().splitlines()
            if line and not line.startswith(('Tag:', 'Generator:', 'Build:'))
        ]
        lines.extend(['Generator: portablepy', 'Build: 1portable'])
        lines.extend(f'Tag: {python_tag}-{abi}-{item}' for item in platform.split('.'))
        wheel_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        for name in ('RECORD', 'RECORD.jws', 'RECORD.p7s'):
            (metadata / name).unlink(missing_ok=True)
        record = StringIO(newline='')
        rows = writer(record, lineterminator='\n')
        record_path = (metadata / 'RECORD').relative_to(root).as_posix()
        with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
            for file in sorted(root.rglob('*')):
                if not file.is_file():
                    continue
                name = file.relative_to(root).as_posix()
                data = file.read_bytes()
                archive.write(file, name)
                if name in modes:
                    archive.getinfo(name).external_attr = modes[name]
                rows.writerow((name, f'sha256={digest(data)}', len(data)))
            rows.writerow((record_path, '', ''))
            archive.writestr(record_path, record.getvalue())
    if destination != path:
        path.unlink()
    wheel_metadata(destination)
    return destination


def collect_wheels(discovery, options, destination: Path, source_copy: Path):
    destination.mkdir(parents=True, exist_ok=True)
    inputs = list(discovery.requirements)
    if discovery.mode == 'project':
        requirement = str(source_copy)
        if options.extras:
            requirement += '[' + ','.join(options.extras) + ']'
        inputs.insert(0, requirement)
    elif discovery.mode == 'wheel':
        inputs.insert(0, str(discovery.source))
        if options.extras:
            inputs[0] += '[' + ','.join(options.extras) + ']'
    elif options.extras:
        raise ValueError('--extra requires a packaged project or wheel')
    for file in discovery.requirement_files:
        inputs.extend(['-r', str(file)])
    if not inputs:
        return
    command = [
        str(discovery.python),
        '-m',
        'pip',
        '--isolated',
        'wheel',
        '--prefer-binary',
        '--wheel-dir',
        str(destination),
    ]
    if options.no_index:
        command.append('--no-index')
    for path in options.find_links:
        command.extend(['--find-links', path])
    run(
        [*command, *inputs],
        cwd=discovery.source.parent if discovery.source.is_file() else discovery.source,
        check=True,
    )
    for path in destination.glob('*.whl'):
        wheel_metadata(path)


def write_requirements(wheels: Path, output: Path):
    lines, names = [], set()
    for path in sorted(wheels.glob('*.whl')):
        metadata = wheel_metadata(path)
        name = sub(r'[-_.]+', '-', metadata['Name']).lower()
        if name in names:
            raise ValueError(f'Multiple wheels for the same distribution: {name}')
        names.add(name)
        lines.append(
            f'{name}=={metadata["Version"]} --hash=sha256:{sha256(path.read_bytes()).hexdigest()}'
        )
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return len(lines)
