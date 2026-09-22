"""Explain a build without creating a distributable or starting its application."""

from pathlib import Path
from re import sub, match
from zlib import compressobj
from tempfile import TemporaryDirectory
from portablepy.discovery import discover
from portablepy.bytecode import compile_tree
from portablepy.files import data_files, copy_sources
from portablepy.launcher import file_hash, COPY_BUFFER_SIZE
from portablepy.output import default_output, output_excludes
from portablepy.wheels import collect_wheels, repack_bytecode, wheel_inventory


def _compressed_size(path):
    compressor = compressobj()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(COPY_BUFFER_SIZE), b''):
            size += len(compressor.compress(block))
    return size + len(compressor.flush())


def _name(requirement):
    found = match(r'[A-Za-z0-9][A-Za-z0-9._-]*', requirement)
    return sub(r'[-_.]+', '-', found[0]).lower() if found else ''


def _dependency_inputs(discovery, options):
    inputs: list[dict] = []
    if discovery.mode in ('project', 'wheel'):
        inputs.append(
            {'requirement': str(discovery.source), 'reason': 'Application package metadata'}
        )
    for requirement in discovery.requirements:
        reasons = []
        if requirement in options.requirements:
            reasons.append('Explicit requirement')
        else:
            for module, evidence in discovery.import_reasons.items():
                for distribution in discovery.runtime['distributions'].get(module, []):
                    origin = discovery.runtime.get('origins', {}).get(_name(distribution))
                    if requirement == origin or _name(requirement) == _name(distribution):
                        reasons.extend(f'{module}: {item}' for item in evidence)
        inputs.append(
            {'requirement': requirement, 'reason': reasons or ['Launch command distribution']}
        )
    inputs.extend(
        {'requirement_file': str(path), 'reason': 'Requirements file'}
        for path in discovery.requirement_files
    )
    return inputs


def inspection_report(options, *, resolve=False):
    discovery = discover(options)
    base = discovery.source if discovery.source.is_dir() else discovery.source.parent
    output = options.output or default_output(discovery, options.command)
    seeds = data_files(options.includes, base)
    application = [
        {
            'path': path.relative_to(base).as_posix(),
            'bytes': path.stat().st_size,
            'reasons': discovery.file_reasons.get(path, ['Selected application source']),
        }
        for path in discovery.application_files
    ]
    seed_entries = [
        {
            'source': str(path),
            'destination': destination.as_posix(),
            'bytes': path.stat().st_size,
            'reason': 'Explicit writable-data seed',
        }
        for destination, path in seeds.items()
    ]
    paths = [*discovery.application_files, *seeds.values()]
    report = {
        'source': str(discovery.source),
        'python': str(discovery.python),
        'mode': discovery.mode,
        'runtime': {
            key: value
            for key, value in discovery.runtime.items()
            if key not in ('stdlib', 'distributions', 'versions', 'origins', 'commands')
        },
        'config': str(options.config) if options.config else None,
        'profile': options.profile,
        'command': list(options.command),
        'output': str(output),
        'inferred_requirements': discovery.requirements,
        'requirement_files': [str(path) for path in discovery.requirement_files],
        'unresolved_imports': discovery.unresolved,
        'application_files': [entry['path'] for entry in application],
        'files': application,
        'seeds': seed_entries,
        'dependency_inputs': _dependency_inputs(discovery, options),
        'resolver': {'index_enabled': not options.no_index, 'find_links': list(options.find_links)},
        'wheels': [],
        'size': {
            'payload_bytes': sum(path.stat().st_size for path in paths),
            'estimated_compressed_payload_bytes': sum(_compressed_size(path) for path in paths),
            'includes_wheels': False,
            'note': 'Payload estimate excludes archive headers, launcher, manifest, and runtime environment. Use --resolve to include resolved wheels and bytecode changes.',
        },
    }
    if not resolve or discovery.unresolved:
        return report
    if options.strip_source and options.compile_mode == 'none':
        raise ValueError('--strip-source requires --compile app or --compile all')
    with TemporaryDirectory(prefix='portablepy-inspect-') as temporary:
        work = Path(temporary)
        source_copy = work / 'source'
        if discovery.mode == 'project':
            copy_sources(
                discovery.source,
                source_copy,
                (*options.excludes, *output_excludes(discovery.source, output)),
            )
        else:
            source_copy.mkdir()
        wheels = work / 'wheels'
        collect_wheels(discovery, options, wheels, source_copy, log_to_stderr=True)
        inventory = wheel_inventory(wheels)
        # Match actual wheel bytes where possible; resolver search locations are not provenance.
        known_wheels = [discovery.source, *(Path(value) for value in discovery.requirements)]
        for record in inventory:
            origin = {
                'kind': 'pip resolver',
                'note': 'Exact download URL is not reported by pip wheel.',
            }
            candidates = [
                *known_wheels,
                *(
                    Path(location) / record['wheel']
                    for location in options.find_links
                    if '://' not in location
                ),
            ]
            for candidate in candidates:
                if candidate.suffix == '.whl' and candidate.is_file():
                    if file_hash(candidate) == record['sha256']:
                        origin = {'kind': 'local wheel', 'path': str(candidate)}
                        break
            record['origin'] = origin
            record['declared_by'] = [
                {'name': parent['name'], 'requirement': requirement}
                for parent in inventory
                for requirement in parent['requires_dist']
                if _name(requirement) == _name(record['name'])
            ]
        app = work / 'app'
        copy_sources(discovery.source, app, paths=discovery.application_files)
        if options.compile_mode != 'none':
            compile_tree(app, discovery.python, strip=options.strip_source)
        if options.compile_mode == 'all':
            origins = {_name(record['name']): record for record in inventory}
            for wheel in sorted(wheels.glob('*.whl')):
                repack_bytecode(
                    wheel, discovery.python, discovery.runtime, strip=options.strip_source
                )
            inventory = wheel_inventory(wheels)
            for record in inventory:
                original = origins[_name(record['name'])]
                record.update(origin=original['origin'], declared_by=original['declared_by'])
        paths = [
            *(path for path in app.rglob('*') if path.is_file()),
            *seeds.values(),
            *wheels.glob('*.whl'),
        ]
        report['wheels'] = inventory
        report['size'] = {
            'payload_bytes': sum(path.stat().st_size for path in paths),
            'estimated_compressed_payload_bytes': sum(_compressed_size(path) for path in paths),
            'includes_wheels': True,
            'note': 'Resolved payload estimate excludes archive headers, launcher, manifest, and runtime environment. Actual ZIP and tar.gz sizes vary.',
        }
    return report
