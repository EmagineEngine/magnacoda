from importlib import metadata

try:
    # Set from the git tag when the package is built or installed (see pyproject.toml).
    __version__ = metadata.version("magnacoda")
except metadata.PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0+unknown"
