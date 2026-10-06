"""Run portablepy with Argly's generated command registry and help."""

from sys import stderr
from tarfile import TarError
from zipfile import BadZipFile
from subprocess import CalledProcessError
from importlib import import_module
from argly import App
from portablepy.generated import REGISTRY, get_help


def __getattr__(name: str):
    if name in ('build', 'inspect', 'verify'):
        return getattr(import_module(f'portablepy.commands.{name}'), name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def main() -> int:
    try:
        return App.from_registry(REGISTRY, help_lookup=get_help).run()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TarError, BadZipFile, CalledProcessError) as error:
        print(f'portablepy: {error}', file=stderr)
        return 1
