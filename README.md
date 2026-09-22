# portablepy

Pack a Python application into a portable ZIP or tar.gz, with its dependency wheels and a small launcher. The recipient supplies Python; the bundle handles its own private environment and offline installation.

Requires CPython 3.14 or later. From this checkout, use `python -m pip install .` to install globally, or run the same command inside a virtual environment. The installed command is `portablepy`.

## Build something

```sh
portablepy build ./my-app --run "python -m my_app" --output my-app.zip
portablepy build ./my-app --run "python -m my_app"
portablepy build ./my-app --run "my-console-command" --output my-app.tar.gz
portablepy build ./script.py --run "python script.py" --output script.zip
portablepy build ./my_app-1.0-py3-none-any.whl --run "python -m my_app" --output my-app.zip
```

`--output` is optional. By default, the archive is created in your current directory using the project and launch target names, platform, architecture, and Python version. For example: `skribblpy-word-guesser-auto-windows-x64-py314.zip`. Windows defaults to ZIP; Linux and macOS default to tar.gz. Existing archives aren't overwritten. Use `--output` to choose another name, location, or supported archive format.

Build on the target operating system and architecture. The tool uses the source project's `.venv` when available, otherwise its own interpreter. Use `--python PATH` to select another interpreter. Each bundle records its Python minor version, architecture, and interpreter ABI. It doesn't include Python itself.

Extract the whole archive, then run:

```sh
python run.py
python run.py --help
```

Arguments after `run.py` are forwarded to your application. Its working directory is the application folder, named with a SHA-256 content hash and recorded in `bundle.json`. The first run verifies files and installs local wheels into `.venv`; subsequent runs reuse it. Moving the folder rebuilds the private environment. Python needs its standard `venv` and `ensurepip` modules.

## Dependencies

Packaged projects and wheels use their declared dependency metadata. The launch command also identifies local examples or scripts that need extra dependencies. For loose applications, discovery starts at the script or module in `--run`, follows local imports, and maps external imports to distributions installed in the selected environment. Installed console commands are mapped to their owning distribution. Local packages are scanned together so command modules discovered at runtime are included; unrelated test and development files aren't used as dependency roots.

You normally don't need `--requirement` or `--find-links`. pip downloads or builds dependency wheels automatically. When an inferred dependency was installed from a local checkout or an available wheel file, the builder uses that source automatically. Local checkouts are copied before building. Install dependencies in the application's `.venv` first so import names can be mapped reliably to distribution names.

A loose application can supply `requirements.txt` instead of inference. Without a launch command, `inspect` scans the whole source directory. Unknown or ambiguous imports are reported instead of guessing PyPI packages. Plugins outside the scanned packages and dynamically constructed imports may still need explicit requirements.

```sh
portablepy inspect ./my-app
portablepy inspect ./my-app --run "python -m my_app"
portablepy build ./my-app --run "python main.py" --output app.zip --requirements requirements.txt
portablepy build ./my-app --run "python -m my_app" --output app.zip --extra cli
portablepy build ./script.py --run "python script.py" --output script.zip --requirement "requests>=2"
```

`--requirement`, `--requirements`, `--extra`, and `--find-links` can be repeated. Explicit requirements replace import inference. pip resolves transitive dependencies and builds any required wheels. Source builds may need compilers and build dependencies on the build machine; recipients only install wheels. `--find-links` is an optional additional package location. Use `--no-index --find-links PATH` when you specifically want to resolve from a prepared local wheel directory.

The builder checks wheel integrity, pins every resolved version and SHA-256 hash, and validates installation in a clean offline environment. It doesn't run your application during a build. The `inspect` command reports the discovery strategy; pip performs the final resolution during `build`.

## Writable data and launch commands

Application-specific state stays out of the bootstrapper. Include seed files under `data/`, then pass their paths through the application's own options:

```sh
portablepy build ./my-app --run "python -m my_app --database {data}/words.json" --include "words.json=data/words.json" --output app.zip
```

Available placeholders are `{bundle}`, `{app}`, `{data}`, `{python}`, and `{bin}`. Included source paths are relative to the project, or the script/wheel's directory. Include directories the same way. Data remains writable and isn't reset during environment setup or relocation. Keep your `data/` folder when updating the bundle.

Launch commands are parsed as argument lists and run without a shell. Use forward slashes for paths inside `--run` and quote arguments containing spaces. Commands may start with `python`, `{python}`, or a console entry point installed by a bundled wheel. Shell pipelines, activation commands, and environment assignments belong in an application wrapper instead.

Project source and resources go in the application folder. Its name hashes every included relative file path and file content after optional compilation. Timestamps and the outer bundle name don't affect this hash. Writable `data/` and dependency wheels live outside that folder and have their own manifest checksums. Use `{app}` when you need its path; the launcher handles the hash automatically.

Packaged projects prefer their installed wheel when importing modules, so generated build files work correctly; loose scripts prefer their bundled source. Common environment, cache, build, editor, and `.env` files are excluded. Add repeatable `--exclude` glob patterns to omit other files. A single-script input copies that script; use its containing directory when it has local modules or resources.

## Bytecode

```sh
portablepy build ./my-app --run "python -m my_app" --output app.zip --compile app
portablepy build ./my-app --run "python -m my_app" --output app.zip --compile all
portablepy build ./my-app --run "python -m my_app" --output app.zip --compile all --strip-source
```

`app` compiles application Python files. `all` also repacks dependency wheels with compiled Python files, refreshed RECORD hashes, and interpreter-specific wheel tags. Source files stay by default. `--strip-source` removes compiled `.py` files and uses adjacent `.pyc` files that Python can import without source. Direct script commands are adjusted to their `.pyc` paths.

Native extensions, package resources, metadata, and licenses are preserved. Wheel-installed script payloads are left intact. Some packages inspect their source or require `.py` resources, so test source removal with your application before distributing it. Bytecode isn't encryption, and it doesn't replace native compilation.

## Verify a bundle

```sh
portablepy verify app.zip
portablepy verify ./extracted-app
python run.py --portable-verify
python run.py --portable-setup
```

Archive verification checks every bundled file, including seed data. Verification of an extracted folder skips writable `data/`. Every launch checks immutable files before installing or starting anything. SHA-256 checks detect corruption; they aren't publisher signatures. Each archive also gets a `.sha256` sidecar.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

MIT licensed. Runtime dependencies: argly. Dependency resolution uses pip from the selected Python environment.
