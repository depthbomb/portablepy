"""Trace local application files while keeping sibling applications out of bundles."""

from pathlib import Path
from fnmatch import fnmatchcase
from ast import walk, parse, Import, ImportFrom
from portablepy.files import selected_files, DEFAULT_EXCLUDES


def trace_sources(
    source: Path, seeds=None, excludes=(), ignored=(), *, file_reasons=None, import_reasons=None
):
    file_reasons = {} if file_reasons is None else file_reasons
    import_reasons = {} if import_reasons is None else import_reasons
    reason = 'Selected source'
    base = source if source.is_dir() else source.parent
    seeds = tuple(seeds) if seeds is not None else (source,)
    roots = tuple(
        dict.fromkeys((*(seed.parent for seed in seeds if seed.is_file()), base, base / 'src'))
    )
    patterns = (*DEFAULT_EXCLUDES, *excludes)
    included: set[Path] = set()
    pending: list[Path] = []
    imports: set[str] = set()
    expanded: set[Path] = set()

    def allowed(path):
        relative = path.relative_to(base)
        candidates = [
            *relative.parts,
            *(parent.as_posix() for parent in (relative, *relative.parents) if parent.parts),
        ]
        return not any(
            fnmatchcase(candidate, pattern) for candidate in candidates for pattern in patterns
        )

    def module_parts(path):
        for root in sorted(roots, key=lambda value: len(value.parts), reverse=True):
            if path.is_relative_to(root):
                relative = path.relative_to(root)
                return relative.with_suffix('').parts if relative.parts else ()
        return ()

    def add_file(path, explanation=None):
        if not allowed(path):
            return
        reasons = file_reasons.setdefault(path, [])
        explanation = explanation or reason
        if explanation not in reasons:
            reasons.append(explanation)
        if path in included:
            return
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError(f'Application file must stay inside its source directory: {path}')
        included.add(path)
        if path.suffix == '.py':
            pending.append(path)

    def add_parents(path):
        for parent in path.parents:
            if parent in roots or not parent.is_relative_to(base):
                break
            initializer = parent / '__init__.py'
            if initializer.is_file():
                add_file(
                    initializer,
                    f'Parent package initializer for {path.relative_to(base).as_posix()}',
                )

    def add_resources(folder):
        # Scripts can read adjacent data files without naming them in an import.
        for path in folder.iterdir():
            if path.is_file() and path.suffix not in ('.py', '.pyc', '.pyo'):
                add_file(path, 'Resource beside the entry script')

    def add(path, whole=True):
        parts = module_parts(path)
        if parts and parts[0] in ignored:
            return
        if not allowed(path):
            return
        add_parents(path)
        if path.is_dir():
            if whole:
                if path in expanded:
                    return
                expanded.add(path)
                for member in selected_files(path, excludes):
                    add_file(member)
            else:
                initializer = path / '__init__.py'
                if initializer.is_file():
                    add_file(initializer)
        else:
            add_file(path)

    def resolve(name, whole=True):
        parts = name.split('.')
        if not name or any(not part.isidentifier() for part in parts):
            return False
        if parts[0] in ignored:
            return True
        for root in roots:
            package = root.joinpath(*parts)
            module = package.with_suffix('.py')
            if module.is_file():
                add(module)
                return True
            if package.is_dir():
                add(package, whole)
                return True
        return False

    for seed in seeds:
        reason = f'Entry point source: {seed.relative_to(base).as_posix()}'
        add(seed)
        if seed.is_file():
            add_resources(seed.parent)
    while pending:
        current = pending.pop()
        try:
            tree = parse(current.read_bytes(), filename=str(current))
        except SyntaxError as error:
            raise ValueError(f'Cannot inspect {current}: {error}') from error
        for node in walk(tree):
            if isinstance(node, (Import, ImportFrom)):
                reason = f'Import in {current.relative_to(base).as_posix()}:{node.lineno}'
            if isinstance(node, Import):
                for alias in node.names:
                    if not resolve(alias.name):
                        external_name = alias.name.split('.')[0]
                        imports.add(external_name)
                        import_reasons.setdefault(external_name, []).append(reason)
            elif isinstance(node, ImportFrom):
                imported_module = node.module or ''
                if node.level:
                    package_parts = module_parts(current)[:-1]
                    prefix = package_parts[: len(package_parts) - node.level + 1]
                    imported_module = (
                        '.'.join((*prefix, imported_module))
                        if imported_module
                        else '.'.join(prefix)
                    )
                if resolve(imported_module, whole=any(alias.name == '*' for alias in node.names)):
                    for alias in node.names:
                        if alias.name != '*':
                            resolve(imported_module + '.' + alias.name)
                elif imported_module:
                    external_name = imported_module.split('.')[0]
                    imports.add(external_name)
                    import_reasons.setdefault(external_name, []).append(reason)
    return tuple(sorted(included)), imports
