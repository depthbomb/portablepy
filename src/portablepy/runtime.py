"""Describe recipient requirements and resolve pinned Python runtime downloads."""

from json import loads
from re import fullmatch
from urllib.request import urlopen
from urllib.parse import urljoin, urlsplit

INDEX_URL = 'https://www.python.org/ftp/python/index-windows.json'
STANDALONE_INDEX_URL = (
    'https://raw.githubusercontent.com/astral-sh/uv/main/crates/uv-python/download-metadata.json'
)
STANDALONE_RELEASES = 'https://github.com/astral-sh/python-build-standalone/releases/download/'


def recipient_runtime(runtime: dict, version: str | None, *, compiled=False) -> dict:
    fields = (
        'implementation',
        'version',
        'platform',
        'machine',
        'bits',
        'free_threaded',
        'cache_tag',
        'magic',
    )
    expected = {key: runtime[key] for key in fields}
    if runtime['platform'] == 'linux':
        expected['libc'] = runtime.get('libc', 'gnu')
    if version is None:
        return expected
    requested = version_parts(version)
    expected['version'] = list(requested[:2])
    expected['free_threaded'] = False
    expected['release_level'] = 'final'
    if len(requested) == 3:
        expected['full_version'] = list(requested)
    if compiled:
        if list(requested[:2]) != runtime['version']:
            raise ValueError(
                "Cross-version bundles require compile = 'none'; bytecode is Python-version-specific"
            )
    else:
        expected.pop('cache_tag')
        expected.pop('magic')
    return expected


def version_parts(value: str) -> tuple[int, ...]:
    if not fullmatch(r'3\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?', value):
        raise ValueError('python-version must look like 3.14 or 3.14.8')
    parts = tuple(map(int, value.split('.')))
    if parts[:2] < (3, 14):
        raise ValueError('python-version must be CPython 3.14 or later')
    return parts


def _official_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != 'https'
        or parsed.netloc != 'www.python.org'
        or not parsed.path.startswith('/ftp/python/')
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f'Expected an official Python download URL: {url}')
    return url


def _open_download(url):
    response = urlopen(_official_url(url), timeout=60)
    try:
        _official_url(response.url)
    except ValueError:
        response.close()
        raise
    return response


def resolve_runtime(version: str, runtime: dict) -> dict:
    if runtime.get('platform', 'win32') != 'win32':
        return _resolve_standalone(version, runtime)
    requested = version_parts(version)
    machine = runtime['machine'].lower()
    if runtime['bits'] == 32 and machine in ('amd64', 'x86_64', 'x86', 'i386', 'i686'):
        architecture = '32'
    elif machine in ('amd64', 'x86_64'):
        architecture = '64'
    elif machine in ('arm64', 'aarch64'):
        architecture = 'arm64'
    else:
        raise ValueError(f'No official Windows runtime is supported for {machine}')

    candidates = []
    visited: set[str] = set()
    url = INDEX_URL
    while url and url not in visited:
        if len(visited) >= 32:
            raise ValueError('Official Python runtime index has too many pages')
        visited.add(url)
        with _open_download(url) as response:
            index = loads(response.read())
        for entry in index.get('versions', []):
            number = entry.get('sort-version', '')
            if not fullmatch(r'3\.[0-9]+\.[0-9]+', number):
                continue
            parts = tuple(map(int, number.split('.')))
            if parts[: len(requested)] != requested:
                continue
            series = '.'.join(map(str, parts[:2]))
            if entry.get('id') != f'pythoncore-{series}-{architecture}':
                continue
            digest = entry.get('hash', {}).get('sha256', '')
            if not fullmatch(r'[0-9a-fA-F]{64}', digest):
                raise ValueError(f'Official Python {number} runtime is missing its SHA-256 hash')
            candidates.append(
                (
                    parts,
                    {
                        'version': number,
                        'architecture': architecture,
                        'url': _official_url(entry['url']),
                        'sha256': digest.lower(),
                    },
                )
            )
        next_page = index.get('next')
        url = urljoin(url, next_page) if next_page else ''

    if not candidates:
        raise ValueError(f'No official stable Windows Python {version} runtime was found')
    return max(candidates, key=lambda item: item[0])[1]


def _open_standalone_index():
    response = urlopen(STANDALONE_INDEX_URL, timeout=60)
    if response.url != STANDALONE_INDEX_URL:
        response.close()
        raise ValueError('Unexpected redirect from the Astral Python download index')
    return response


def _resolve_standalone(version: str, runtime: dict) -> dict:
    requested = version_parts(version)
    target = runtime['platform']
    machine = runtime['machine'].lower()
    architecture = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
    if (
        target not in ('linux', 'darwin')
        or runtime['bits'] != 64
        or architecture not in ('x86_64', 'aarch64')
    ):
        raise ValueError(f'No standalone Python runtime is supported for {target} {machine}')
    libc = runtime.get('libc', 'gnu') if target == 'linux' else 'none'
    with _open_standalone_index() as response:
        index = loads(response.read())
    candidates = []
    for entry in index.values():
        arch = entry.get('arch', {})
        if (
            entry.get('name') != 'cpython'
            or entry.get('os') != target
            or arch.get('family') != architecture
            or arch.get('variant')
            or entry.get('libc') != libc
            or entry.get('prerelease')
            or entry.get('variant')
        ):
            continue
        parts = tuple(entry.get(key) for key in ('major', 'minor', 'patch'))
        if any(type(part) is not int for part in parts) or parts[: len(requested)] != requested:
            continue
        url = entry.get('url', '')
        parsed = urlsplit(url)
        if (
            not url.startswith(STANDALONE_RELEASES)
            or not parsed.path.endswith('-install_only_stripped.tar.gz')
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError('Expected an Astral standalone Python release URL')
        digest = entry.get('sha256', '')
        if not fullmatch(r'[0-9a-fA-F]{64}', digest):
            raise ValueError('Astral Python runtime is missing its SHA-256 hash')
        build = entry.get('build', '')
        if not fullmatch(r'[0-9]{8}', build):
            raise ValueError('Invalid Astral Python build identifier')
        candidates.append(
            (
                parts,
                build,
                {
                    'version': '.'.join(map(str, parts)),
                    'architecture': architecture,
                    'platform': target,
                    'libc': libc,
                    'provider': 'astral',
                    'build': build,
                    'url': url,
                    'sha256': digest.lower(),
                },
            )
        )
    if not candidates:
        raise ValueError(
            f'No stable Astral Python {version} runtime was found for {target} {architecture} {libc}'
        )
    return max(candidates, key=lambda item: (item[0], item[1]))[2]
