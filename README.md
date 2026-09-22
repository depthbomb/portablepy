# portablepy

Pack a Python application into a portable ZIP or tar.gz, with its dependency wheels and a small launcher. The recipient supplies Python; the bundle handles its own private environment and offline installation.

Requires CPython 3.14 or later. From this checkout, use `python -m pip install .` to install globally, or run the same command inside a virtual environment. The installed command is `portablepy`.

## Build something

```sh
portablepy build ./my-app --run "python -m my_app" --output my-app.zip
portablepy build ./my-app --run "my-console-command" --output my-app.tar.gz
portablepy build ./script.py --run "python script.py" --output script.zip
portablepy build ./my_app-1.0-py3-none-any.whl --run "python -m my_app" --output my-app.zip
```

Build on the target operating system and architecture. The tool uses the source project's `.venv` when available, otherwise its own interpreter. Use `--python PATH` to select another interpreter. Each bundle records its Python minor version, architecture, and interpreter ABI. It doesn't include Python itself.

Extract the whole archive, then run:

```sh
python run.py
python run.py --help
```

Arguments after `run.py` are forwarded to your application. Its working directory is `app/`. The first run verifies files and installs local wheels into `.venv`; subsequent runs reuse it. Moving the folder rebuilds the private environment. Python needs its standard `venv` and `ensurepip` modules.

## Dependencies

Packaged projects and wheels use their declared dependency metadata. A directory or script can supply `requirements.txt`; otherwise the tool scans imports and maps them to distributions installed in the selected environment. It follows local imports and reports unresolved or ambiguous names instead of guessing PyPI packages. Dynamic imports and optional plugins may need explicit requirements.

```sh
portablepy inspect ./my-app
portablepy build ./my-app --run "python main.py" --output app.zip --requirements requirements.txt
portablepy build ./my-app --run "python -m my_app" --output app.zip --extra cli
portablepy build ./script.py --run "python script.py" --output script.zip --requirement "requests>=2"
```

`--requirement`, `--requirements`, `--extra`, and `--find-links` can be repeated. Explicit requirements replace import inference for loose scripts. pip resolves transitive dependencies and builds any required wheels. Source builds may need compilers and build dependencies on the build machine; recipients only install wheels. Use `--no-index --find-links PATH` to build from local packages.

The builder checks wheel integrity, pins every resolved version and SHA-256 hash, and validates installation in a clean offline environment. It doesn't run your application during a build. The `inspect` command reports the discovery strategy; pip performs the final resolution during `build`.

## Writable data and launch commands

Application-specific state stays out of the bootstrapper. Include seed files under `data/`, then pass their paths through the application's own options:

```sh
portablepy build ./my-app --run "python -m my_app --database {data}/words.json" --include "words.json=data/words.json" --output app.zip
```

Available placeholders are `{bundle}`, `{app}`, `{data}`, `{python}`, and `{bin}`. Included source paths are relative to the project, or the script/wheel's directory. Include directories the same way. Data remains writable and isn't reset during environment setup or relocation. Keep your `data/` folder when updating the bundle.

Launch commands are parsed as argument lists and run without a shell. Use forward slashes for paths inside `--run` and quote arguments containing spaces. Commands may start with `python`, `{python}`, or a console entry point installed by a bundled wheel. Shell pipelines, activation commands, and environment assignments belong in an application wrapper instead.

Project source and resources go under `app/`. Packaged projects prefer their installed wheel when importing modules, so generated build files work correctly; loose scripts prefer their bundled source. Common environment, cache, build, editor, and `.env` files are excluded. Add repeatable `--exclude` glob patterns to omit other files. A single-script input copies that script; use its containing directory when it has local modules or resources.

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
