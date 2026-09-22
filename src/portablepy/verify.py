"""Verify archives without extracting or executing their contents."""

from json import loads
from pathlib import Path
from hashlib import sha256
from tarfile import TarFile
from zipfile import ZipFile
from tarfile import open as open_tar
from portablepy.files import portable_path
from portablepy.launcher import MANIFEST, verify_files, load_manifest, validate_manifest


def verify_bundle(path: Path):
    path = path.expanduser().resolve()
    if path.is_dir():
        manifest = load_manifest(path)
        verify_files(path, manifest)
        return manifest
    archive: ZipFile | TarFile = (
        ZipFile(path) if path.name.endswith('.zip') else open_tar(path, 'r:gz')
    )
    with archive:

        def read(member_name):
            if isinstance(archive, ZipFile):
                return archive.read(member_name)
            stream = archive.extractfile(member_name)
            if stream is None:
                raise ValueError(f'Unreadable member: {member_name}')
            with stream:
                return stream.read()

        if isinstance(archive, ZipFile):
            names = archive.namelist()
        else:
            members = archive.getmembers()
            if any(not member.isfile() for member in members):
                raise ValueError('Bundle archives must contain regular files only')
            names = [member.name for member in members]

        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive members')
        for name in names:
            portable_path(name)
        roots = {name.split('/')[0] for name in names}
        if len(roots) != 1:
            raise ValueError('Expected one bundle directory')
        prefix = next(iter(roots)) + '/'
        raw = read(prefix + MANIFEST)
        expected = read(prefix + MANIFEST + '.sha256').decode().strip()
        if sha256(raw).hexdigest() != expected:
            raise ValueError('Bundle manifest checksum failed')
        manifest = loads(raw)
        validate_manifest(manifest)
        expected_names = {prefix + name for name in manifest['files']} | {
            prefix + MANIFEST,
            prefix + MANIFEST + '.sha256',
        }
        if set(names) != expected_names:
            raise ValueError('Archive files do not match the manifest')
        for name, expected in manifest['files'].items():
            portable_path(name)
            if sha256(read(prefix + name)).hexdigest() != expected:
                raise ValueError(f'Bundle checksum failed: {name}')
        return manifest
