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

`--output` is optional. By default, the archive is created in your current directory using the project and launch target names, platform, architecture, and Python version. For example: `skribblpy-word-guesser-auto-windows-x64-py314.zip`. Windows defaults to ZIP; Linux and macOS default to tar.gz. Existing archives aren't overwritten unless you pass `--replace`. Use `--output` to choose another name, location, or supported archive format.

Build on the target operating system and architecture. The tool uses the source project's `.venv` when available, otherwise its own interpreter. Use `--python PATH` to select another interpreter. Each bundle records its Python minor version, architecture, and interpreter ABI. It doesn't include Python itself.

Extract the whole archive, then run:

```sh
python run.py
python run.py --help
```

Arguments after `run.py` are forwarded to your application. Its working directory is the application folder, named with a SHA-256 content hash and recorded in `bundle.json`. The first run verifies files and installs local wheels into `.venv`; subsequent runs reuse it. Moving the folder rebuilds the private environment. Python needs its standard `venv` and `ensurepip` modules.

## Save your build settings

Put defaults in your project's `pyproject.toml` so you don't have to remember a long command:

```toml
[tool.portablepy]
source = 'my-app'
run = 'python -m my_app --database {data}/words.json'
include = ['defaults/words.json=data/words.json']

[tool.portablepy.profiles.release]
compile = 'all'
strip-source = true
```

```sh
portablepy build
portablepy build --profile release
portablepy inspect --profile release --resolve
portablepy build --profile release --keep-source --replace
```

The nearest `pyproject.toml` is found starting at the source you supplied, or your current directory. Use `--config PATH` to select one explicitly. With configuration and no source argument, `source` defaults to the configuration directory. Configured paths are relative to that directory. An omitted `output` still defaults to the current working directory.

Profile settings override defaults, and command-line options override both. Lists replace the earlier list rather than appending to it. Use `--keep-source`, `--use-index`, or `--no-replace` to turn off the corresponding profile setting. Settings use the CLI names: `run`, `source`, `output`, `python`, `compile`, `strip-source`, `no-index`, and `replace`. The repeatable options `requirement`, `requirements`, `extra`, `include`, `exclude`, and `find-links` take TOML lists.

`--replace` finishes the new build and its offline installation check before publishing. The archive is replaced atomically; validation or publication failures keep the previous archive. Its checksum sidecar is updated too. Replacement needs enough free space to stage a complete new archive alongside the old one.

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

The builder checks wheel integrity, pins every resolved version and SHA-256 hash, and validates installation in a clean offline environment. It doesn't run your application during a build. `inspect` returns JSON with selected files, inclusion reasons, import locations, dependency inputs, writable seeds, and a compressed payload estimate. It also shows the selected configuration, profile, interpreter, and output path.

Add `--resolve` to download or build the wheel set, report versions, hashes, dependency declarations, and known local wheel origins, and estimate the payload after bytecode compilation. pip logs go to stderr, leaving stdout as JSON. Resolver search locations are reported separately; an exact download origin isn't claimed when pip doesn't supply one. Resolution can run package build backends, but doesn't start your application. Size estimates exclude the launcher, manifest, archive headers, and the private environment created after extraction.

## Writable data and launch commands

Application-specific state stays out of the bootstrapper. Include seed files under `data/`, then pass their paths through the application's own options:

```sh
portablepy build ./my-app --run "python -m my_app --database {data}/words.json" --include "words.json=data/words.json" --output app.zip
```

Available placeholders are `{bundle}`, `{app}`, `{data}`, `{python}`, and `{bin}`. Included source paths are relative to the project, or the script/wheel's directory. Include directories the same way. Defaults ship in immutable `seeds/` files. At setup or launch, the bootstrapper copies each seed into `data/` only if its destination is missing. Existing files keep their contents, including when a new bundle changes its defaults. New seed destinations are added automatically; deleting a live file restores its default on the next launch.

Extract an update into the same bundle folder to preserve `data/`. Archives contain no live `data/` files, so extraction won't replace learned databases or settings. If moving an update into a new folder instead, copy your existing `data/` there before launching. Seed files are checked for corruption on every launch.

Launch commands are parsed as argument lists and run without a shell. Use forward slashes for paths inside `--run` and quote arguments containing spaces. Commands may start with `python`, `{python}`, or a console entry point installed by a bundled wheel. Shell pipelines, activation commands, and environment assignments belong in an application wrapper instead.

The application folder contains the local package selected by `--run`, its resources, imported local helpers, and parent package initializers. Selecting `python -m examples.word_guesser` includes that example without copying sibling examples, repository tests, or build files. `inspect --run "..."` lists the application files before you build.

The folder name hashes every included relative file path and file content after optional compilation. Timestamps and the outer bundle name don't affect this hash. Writable `data/` and dependency wheels live outside that folder and have their own manifest checksums. Use `{app}` when you need its path; the launcher handles the hash automatically.

Packaged project code is supplied by its wheel, so generated build files work correctly. The full project is copied only into a temporary directory for its build backend. Loose scripts include their imported local helpers and adjacent data files. Common environment, cache, build, editor, and `.env` files are excluded. Add repeatable `--exclude` glob patterns to omit other files. Dynamic imports outside the selected package may need an application wrapper or declared package metadata.

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
python run.py --portable-info
```

Archive verification checks every bundled file, including seed data. Verification of an extracted folder skips writable `data/`. Every launch checks immutable files before installing or starting anything. SHA-256 checks detect corruption; they aren't publisher signatures. Each archive also gets a `.sha256` sidecar.

`--portable-info` prints JSON with the bundle name, build ID, required runtime, launch command, application directory, compilation settings, dependency versions and hashes, and seed destinations. It checks immutable files but doesn't create an environment, initialize data, or start the application. You can inspect a bundle's metadata even when your interpreter doesn't match its target runtime.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
```

MIT licensed. Runtime dependencies: argly. Dependency resolution uses pip from the selected Python environment.
