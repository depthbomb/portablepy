# portablepy

Bundle a Python app into a ZIP or tar.gz with its dependencies and a launcher. Share the archive, extract it, and run it. Dependencies install offline from the bundled wheels.

Build and inspection settings live in a project-local `portablepy.toml`. Specify the recipient's Python version to let the launcher reuse or download a runtime when no matching installation is available.

## Install

The tool requires CPython 3.14 or later. Create a virtual environment with `python -m venv .venv`, then activate it with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` in a Unix shell:

```sh
python -m pip install portablepy
```

## Build an app

Create `portablepy.toml` beside your script:

```toml
source = 'main.py'
run = 'python main.py'
```

Then run:

```sh
portablepy build
```

For a directory, packaged project, or wheel, change the configuration:

```toml
source = 'my-app'
run = 'python -m my_app'
output = 'dist/my-app.zip'
```

A wheel can use `source = 'my_app-1.0-py3-none-any.whl'` and `run = 'my-console-command'`.

Build on the operating system and architecture your users have. portablepy uses the app's `.venv` when available, or its own Python interpreter otherwise. The `python` setting can select a different build interpreter.

Without `output`, the archive is written beside the config file. Its name includes the app, recipient platform, architecture, and Python series. Windows gets a ZIP; Linux and macOS get a tar.gz. Set `replace = true` to replace an existing archive after the new build passes its checks.

## Choose the recipient's Python

```toml
source = 'main.py'
run = 'python main.py'
python-version = '3.14'
```

`python-version` applies to the recipient, not the interpreter running the build. It accepts a stable CPython series such as `'3.14'` or an exact release such as `'3.14.8'`. Supported recipient versions start at 3.14. The application itself must support the selected version.

The setup helper looks for a matching installed Python on PATH, and also uses the Python launcher on Windows. It checks architecture and runtime compatibility. A series accepts any stable patch in that series; an exact release requires that patch. If no suitable installation is available, the helper looks in portablepy's shared runtime cache before downloading anything. It doesn't install Python globally or change PATH.

The build records a specific fallback release, URL, and SHA-256 hash. A series selects the latest available stable patch from the provider's index when building. A matching cached patch is reused even if the fallback is newer. Downloads must match their pinned hash.

Windows downloads come from the [official Python runtime index](https://www.python.org/ftp/python/index-windows.json). The general-purpose runtime ZIP retains `venv`, `ensurepip`, pip, and Tcl/Tk; documentation, headers, and development libraries are omitted from the extracted copy. The smaller [embeddable distribution](https://docs.python.org/3.14/using/windows.html#the-embeddable-package) omits pip and Tcl/Tk and doesn't support this tool's dependency setup.

macOS and Linux use [Astral's python-build-standalone](https://github.com/astral-sh/python-build-standalone) releases, selected from the same [download metadata used by uv](https://github.com/astral-sh/uv/blob/main/crates/uv-python/download-metadata.json). The `install_only_stripped` archives omit build artifacts and debug symbols. Setup also removes headers, manual pages, and the top-level static Python library. Intel/AMD x86-64 and ARM64 are supported; Linux downloads match the builder's glibc or musl environment.

Runtimes are shared by bundles belonging to the same user:

| Platform | Cache directory | Example runtime folder |
| --- | --- | --- |
| Windows | `%LOCALAPPDATA%\portablepy` | `python-3.14.8-64` |
| macOS | `~/Library/Application Support/portablepy` | `python-3.14.8-aarch64` |
| Linux | `$XDG_DATA_HOME/portablepy`, or `~/.local/share/portablepy` | `python-3.14.8-x86_64-gnu` |

Folder names include the exact version and architecture. Linux also includes `gnu` or `musl` to keep incompatible runtimes separate. Windows architecture names follow the official index: `32`, `64`, or `arm64`. Moving an application folder keeps using the shared runtime; each application still has its own private `.venv` for dependencies.

The first download requires internet access. Once a suitable Python is installed or cached, launching and dependency installation work offline. `no-index` controls dependency package lookup, not the Python release index or runtime download.

Omitting `python-version` requires an installed Python matching the build environment's series and runtime characteristics.

For configured recipient versions, dependency wheels are selected for that version. Dependencies must have compatible wheels; local projects are built with the builder's interpreter, so native projects may need a prebuilt wheel for the recipient version. Python-conditional dependency markers are evaluated by pip on the build machine; declare the recipient's dependencies explicitly when those differ, and test the bundle on the recipient version. Cross-series builds require `compile = 'none'`. When the builder's runtime doesn't match the recipient requirements, offline installation is checked on first launch rather than during the build.

## Run the bundle

Extract the whole archive somewhere writable, open a terminal in that folder, and run:

```sh
python run.py
python run.py --help
```

Arguments go straight to your app. With `compile = 'all'`, use `python run.pyc` instead; compiled launchers require a compatible Python before they can start.

Bundles with `python-version` include a setup helper. If Python is missing or incompatible, run it once from the extracted folder. On Windows, use PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./python-setup.ps1
if ($LASTEXITCODE -eq 0) {
    ./run.cmd
}
```

On Linux:

```sh
sh ./python-setup.sh && ./run.sh
```

On macOS:

```sh
sh ./python-setup.sh && ./run.command
```

Unix setup needs `curl`, `tar`, and either `sha256sum` or `shasum`, along with standard shell utilities. It does not require a compiler.

Setup creates the appropriate launch script after finding or downloading a suitable Python. Use that script for later launches and append application arguments normally. It handles `run.py` or `run.pyc` automatically. If an existing script wasn't created by portablepy, setup leaves it alone.

The bundle remembers its selected Python in `.portablepy-python`. Later launches reuse that selection without searching installed versions again. Updating the bundle or changing the interpreter invalidates the marker, so the launcher can select a suitable runtime again.

When `run.py` starts under an incompatible Python that can execute the launcher, it calls the setup helper automatically, creates the convenience script, and restarts with the selected runtime. A compatible installed Python launches directly without creating an extra script.

The first launch checks the bundled files and creates a private `.venv` using the included wheels. Later launches reuse it. Moving the bundle or updating it rebuilds the environment as needed. Python needs its standard `venv` and `ensurepip` modules.

## Configuration

portablepy looks for the nearest `portablepy.toml`, starting in the current directory and searching its parents. You can select a different file directly:

```sh
portablepy build ./release.toml
portablepy inspect ./release.toml
```

All configured file paths are relative to the config file. Launch-command paths are relative to the bundled application folder. Use TOML strings for individual values, arrays for repeated values, and `true` or `false` for switches.

| Setting | Meaning | Default |
| --- | --- | --- |
| `source` | Application directory, script, project, or wheel | Config directory |
| `run` | Application launch command | Required |
| `output` | ZIP or tar.gz archive path | Generated name beside config |
| `python` | Path to the build interpreter | App's `.venv`, then portablepy's interpreter |
| `python-version` | Recipient's Python series or exact release | Match build runtime |
| `requirement` | Array of package requirements or local package paths | Import discovery or package metadata |
| `requirements` | Array of requirements-file paths | Adjacent `requirements.txt` for loose apps |
| `extra` | Array of packaged application extras | `[]` |
| `include` | Array of writable defaults as `SOURCE=data/DESTINATION` | `[]` |
| `exclude` | Array of source exclusion patterns | `[]`, plus built-in exclusions |
| `find-links` | Array of local wheel directories or package listing URLs | `[]` |
| `no-index` | Resolve dependencies from local packages only | `false` |
| `compile` | Bytecode scope: `'none'`, `'app'`, or `'all'` | `'none'` |
| `strip-source` | Remove compiled `.py` files; requires compilation | `false` |
| `replace` | Replace an existing archive after build checks | `false` |
| `resolve` | Include resolved wheels in inspection reports | `false` |
| `profile` | Name of a profile defined in this file | None |

Optional profiles override the top-level settings. Arrays replace earlier arrays. Select the profile inside the file:

```toml
source = 'my-app'
run = 'python -m my_app'
profile = 'release'

[profiles.release]
compile = 'all'
strip-source = true
replace = true
```

## Dependencies and files

For packaged projects and wheels, portablepy reads the package's dependency metadata. For scripts, it follows local imports and looks up dependencies in the build environment. Install your app's dependencies there before building, or declare them explicitly:

```toml
source = 'main.py'
run = 'python main.py'
requirement = ['requests>=2']
# Alternatively: requirements = ['requirements.txt']
```

Explicit requirements replace import-based dependency detection. Dynamic imports and plugins may need this. For packaged extras, use `extra = ['cli']`. For local dependency packages only, set `no-index = true` and `find-links = ['wheels']`.

The bundle includes the selected app's local helpers and resources. Common cache, environment, build, and editor files are excluded, along with `.env` files. Use `exclude = ['*.log']` to leave out additional files.

To see what's included before building:

```sh
portablepy inspect
```

`inspect` reports files, dependencies, recipient runtime requirements, and estimated size as JSON. Set `resolve = true` in the config to also download or build dependency wheels for a fuller report. Inspection doesn't create a distributable or start your app. Building checks wheel integrity and, when the local interpreter matches the recipient requirements, tests installation in a clean offline environment; it doesn't start your app.

## Keep writable data

```toml
source = 'my-app'
run = 'python -m my_app --config {data}/settings.json'
include = ['settings.json=data/settings.json']
```

Files and directories both work. Defaults live in `seeds/` and are copied into `data/` only when missing. Extracting an update into the same bundle folder keeps existing data. When moving to a fresh folder, copy `data/` over before launching.

Launch commands support `{bundle}`, `{app}`, `{data}`, `{python}`, and `{bin}` placeholders. The app runs from its application folder, which is named after a content hash. Use `{app}` instead of hardcoding that folder name.

Commands are argument lists, so use forward slashes for paths and quote arguments containing spaces. Shell pipelines and activation commands aren't supported.

## Compile to bytecode

```toml
source = 'my-app'
run = 'python -m my_app'
compile = 'all'
strip-source = true
```

`compile = 'app'` compiles application files. `'all'` also compiles dependency wheels and creates `run.pyc`. Sources stay unless `strip-source = true`.

Compilation keeps assertions and docstrings at optimization level 0. Native extensions, resources, and dependency licenses stay in the bundle. Some packages need their source files at runtime, so test your app before distributing a source-stripped build. Bytecode is specific to the Python series and doesn't hide your code securely.

## Check a bundle

```sh
portablepy verify app.zip
portablepy verify ./extracted-app
python run.py --portable-info
python run.py --portable-setup
python run.py --portable-verify
```

Use `run.pyc` for bundles built with `compile = 'all'`. After runtime setup, you can also pass these arguments to the generated script, such as `./run.cmd --portable-verify` on Windows or `./run.sh --portable-verify` on Linux.

`--portable-info` shows bundle details without setting up the application environment. `--portable-setup` prepares the environment without starting the app. `--portable-verify` checks bundled files and leaves writable data alone.

Each archive includes checksums and gets a `.sha256` sidecar. These detect damaged or changed files; they don't prove who published the bundle.

## Migrating existing builds

Build and inspect no longer accept option flags or source paths. Move settings from `[tool.portablepy]` in `pyproject.toml` into a dedicated `portablepy.toml`, without that table header. Rename `[tool.portablepy.profiles.release]` to `[profiles.release]` and choose it with `profile = 'release'` at the top of the file.

Former flags use the same names as config keys: `--run` becomes `run`, `--strip-source` becomes `strip-source = true`, and repeated `--requirement` values become a `requirement` array. Use `strip-source = false`, `no-index = false`, and `replace = false` instead of the old inverse flags. `--command` maps to `run`, `-o` to `output`, and `--compile-mode` to `compile`. Supply a config path as the positional argument instead of `--config`.

## Development

Activate the project's `.venv`, then run:

```sh
python -m pip install -e ".[dev]"
python -m pytest --cov=portablepy --cov-branch
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m argly gen --package portablepy.commands --name portablepy --output src/portablepy/generated.py --check
```

Regenerate `src/portablepy/generated.py` with the same Argly command without `--check` after changing command definitions or help text.
