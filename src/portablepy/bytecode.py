"""Compile application and wheel sources with the selected interpreter."""

from pathlib import Path
from subprocess import run

COMPILE = """
from sys import argv
from pathlib import Path
from py_compile import compile, PycInvalidationMode
from importlib.util import cache_from_source
root, strip = Path(argv[1]), argv[2] == 'strip'
for path in sorted(root.rglob('*.py')):
    relative = path.relative_to(root)
    if '__pycache__' in relative.parts or any(part.endswith('.dist-info') for part in relative.parts):
        continue
    if any(part.endswith('.data') for part in relative.parts) and 'scripts' in relative.parts:
        continue
    output = str(path.with_suffix('.pyc')) if strip else cache_from_source(str(path))
    compile(str(path), cfile=output, dfile=relative.as_posix(), doraise=True,
            invalidation_mode=PycInvalidationMode.CHECKED_HASH)
    if strip:
        path.unlink()
"""


def compile_tree(root: Path, python: Path, *, strip=False):
    run([str(python), '-I', '-c', COMPILE, str(root), 'strip' if strip else 'keep'], check=True)
