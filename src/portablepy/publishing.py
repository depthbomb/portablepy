"""Publish a fully validated archive without discarding the previous build."""

from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from portablepy.output import validate_output
from portablepy.launcher import file_hash, COPY_BUFFER_SIZE


def publish_archive(staged: Path, output: Path, *, replace=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_name(output.name + '.lock')
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as error:
        raise ValueError(
            f'Another build is publishing {output}; check {lock} before retrying'
        ) from error
    try:
        with handle:
            handle.write('portablepy publish\n')
        validate_output(output, replace=replace)
        checksum = output.with_name(output.name + '.sha256')
        if checksum.is_symlink() or (checksum.exists() and not checksum.is_file()):
            raise ValueError(f'Checksum output must be a regular file: {checksum}')
        # Staging beside the destination keeps replacement on the same filesystem.
        with TemporaryDirectory(prefix='.portablepy-publish-', dir=output.parent) as temporary:
            folder = Path(temporary)
            archive = folder / output.name
            sidecar = folder / checksum.name
            backup = folder / 'previous-checksum'
            copyfile(staged, archive)
            sidecar.write_text(f'{file_hash(archive)}  {output.name}\n', encoding='utf-8')
            existed = checksum.exists()
            if existed:
                copyfile(checksum, backup)
            sidecar.replace(checksum)
            try:
                if replace:
                    archive.replace(output)
                else:
                    # A hard link creates the complete file atomically and cannot overwrite.
                    # Use exclusive copying on filesystems without hard link support.
                    try:
                        output.hardlink_to(archive)
                    except FileExistsError:
                        raise
                    except OSError:
                        with output.open('xb') as target:
                            try:
                                with archive.open('rb') as source:
                                    for block in iter(lambda: source.read(COPY_BUFFER_SIZE), b''):
                                        target.write(block)
                            except BaseException:
                                target.close()
                                output.unlink()
                                raise
            except BaseException:
                if existed:
                    backup.replace(checksum)
                else:
                    checksum.unlink(missing_ok=True)
                raise
    finally:
        lock.unlink(missing_ok=True)
