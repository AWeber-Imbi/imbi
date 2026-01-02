"""
Imbi
====

Imbi is a DevOps Service Management Platform designed to provide an efficient
way to manage a large environment that contains many services and applications.

"""

from importlib import metadata

try:
    version = metadata.version('imbi')
except metadata.PackageNotFoundError:
    version = '0.0.0'
