"""Imbi common library - shared functionality for Imbi ecosystem."""

from importlib import metadata

try:
    version = metadata.version('imbi-common')
except metadata.PackageNotFoundError:
    version = '0.0.0'

del metadata
