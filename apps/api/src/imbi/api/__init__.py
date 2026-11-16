"""
Imbi
====

Imbi is the open-source service catalog that tracks every service's
ownership, deployments, and health, and runs the AI agents and workflows
that fix them.

"""

from importlib import metadata

try:
    version = metadata.version('imbi-api')
except metadata.PackageNotFoundError:
    version = '0.0.0'
