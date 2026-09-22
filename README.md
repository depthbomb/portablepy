# portablepy

Bundle a Python app into a ZIP or tar.gz with its dependencies and a launcher. Share the archive, extract it, and run it. The bundle sets up its own environment and installs dependencies offline.

Python itself isn't included. The person running the app needs a matching CPython version, operating system, and architecture.

## Install

Requires CPython 3.14 or later. Install it in a virtual environment:

```sh
python -m pip install portablepy
```

## Build an app

```sh
portablepy build ./my-app --run "python -m my_app"
portablepy build ./script.py --run "python script.py" --output app.zip
portablepy build ./my_app-1.0-py3-none-any.whl --run "my-console-command"
```

Build on the operating system and architecture your users have. portablepy uses the app's `.venv` when available, or its own Python interpreter otherwise. Use `--python PATH` to choose one.

Without `--output`, the filename includes the app name, platform, architecture, and Python version. Windows gets a ZIP; Linux and macOS get a tar.gz. Use `--replace` to replace an existing archive after the new build passes validation.

## Run the bundle

Extract the whole archive somewhere writable, then double-click `run.cmd` on Windows or `run.command` on macOS. Linux bundles include `run.sh`; your file manager may need permission to run executable scripts.

You can also use a terminal:

```sh
python run.py
python run.py --help
```

Arguments go straight to your app. With `--compile all`, the launcher is `run.pyc`; use `python run.pyc` instead. The double-click launcher picks the right file automatically.

The first launch checks the bundled files and creates a private `.venv` using the included wheels. Later launches reuse it. Moving the bundle or updating it rebuilds the environment as needed. Python needs its standard `venv` and `ensurepip` modules.

If extraction removes executable permissions on macOS or Linux, run `chmod +x run.command` or `chmod +x run.sh`.

## Dependencies and files

For packaged projects and wheels, portablepy reads the package's dependency metadata. For scripts, it follows local imports and looks up dependencies in the selected Python environment. Install your app's dependencies there before building.

A `requirements.txt` beside a script or in a loose app directory supplies explicit dependencies. You can also pass them yourself:

```sh
portablepy build ./my-app --run "python main.py" --requirements requirements.txt
portablepy build ./my-app --run "python -m my_app" --extra cli
portablepy build ./script.py --run "python script.py" --requirement "requests>=2"
```

Explicit requirements replace import-based dependency detection. Dynamic imports and plugins may need this. Use `--no-index --find-links ./wheels` to build from local packages only.

The bundle includes the selected app's local helpers and resources. Common cache, environment, build, and editor files are excluded, along with `.env` files. Add `--exclude` patterns to leave out other files.

To see what's included before building:

```sh
portablepy inspect ./my-app --run "python -m my_app"
portablepy inspect ./my-app --run "python -m my_app" --resolve
```

`inspect` reports files, dependencies, and estimated size as JSON. `--resolve` also downloads or builds the wheels for a fuller report. Building checks wheel integrity and tests installation in a clean offline environment; it doesn't start your app.

## Keep writable data

Use `--include SOURCE=data/DESTINATION` for default settings, databases, or other files your app changes:

```sh
portablepy build ./my-app --run "python -m my_app --config {data}/settings.json" --include "settings.json=data/settings.json"
```

Files and directories both work. Defaults live in `seeds/` and are copied into `data/` only when missing. Extracting an update into the same bundle folder keeps existing data. When moving to a fresh folder, copy `data/` over before launching.

Launch commands support `{bundle}`, `{app}`, `{data}`, `{python}`, and `{bin}` placeholders. The app runs from its application folder, which is named after a content hash. Use `{app}` instead of hardcoding that folder name.

Commands are argument lists, so use forward slashes for paths and quote arguments containing spaces. Shell pipelines and activation commands aren't supported.

## Save build settings

Put defaults and optional profiles in `pyproject.toml`:

```toml
[tool.portablepy]
source = 'my-app'
run = 'python -m my_app --config {data}/settings.json'
include = ['defaults/settings.json=data/settings.json']

[tool.portablepy.profiles.release]
compile = 'all'
strip-source = true
```

```sh
portablepy build
portablepy build --profile release
portablepy inspect --profile release --resolve
```

portablepy looks for the nearest `pyproject.toml`, starting from your source or current directory. Use `--config PATH` to choose one. Configured paths are relative to that file; the default output stays in your current directory.

Profiles override defaults, and command-line options override profiles. Lists replace earlier lists. Use `--keep-source`, `--use-index`, or `--no-replace` to turn off those profile settings.

## Compile to bytecode

```sh
portablepy build ./my-app --run "python -m my_app" --compile all --strip-source
```

- `--compile app` compiles your application files.
- `--compile all` also compiles dependency wheels and creates `run.pyc`.
- `--strip-source` removes compiled `.py` files, including `run.py` with `all`. Sources stay by default.

Compilation keeps assertions and docstrings at optimization level 0. Native extensions, resources, and dependency licenses stay in the bundle. Some packages need their source files at runtime, so test your app before distributing a source-stripped build. Bytecode is specific to the Python version and doesn't hide your code securely.

## Check a bundle

```sh
portablepy verify app.zip
portablepy verify ./extracted-app
python run.py --portable-info
python run.py --portable-setup
python run.py --portable-verify
```

Use `run.pyc` for bundles built with `--compile all`.

`--portable-info` shows bundle details without setting anything up. `--portable-setup` prepares the environment without starting the app. `--portable-verify` checks bundled files and leaves writable data alone.

Each archive includes checksums and gets a `.sha256` sidecar. These detect damaged or changed files; they don't prove who published the bundle.

## Development

Create a `.venv` with `python -m venv .venv`. Activate it with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in a Unix shell, then run:

```sh
python -m pip install -e ".[dev]"
python -m pytest --cov=portablepy --cov-branch
python -m ruff check .
python -m ruff format --check .
python -m mypy
```
