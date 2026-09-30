"""The mapping modules: one module for each target table.

A module ``<table>.py`` in this package has a ``MAPPING`` attribute that
satisfies :class:`imbi.common.db.etl.mapping.Mapping`, with ``table``
equal to the module name. :func:`discover` imports every module whose
name does not start with ``_``, so a new mapping is a new file and
nothing else.

``_pending.py`` lists the tables that do not have a mapping yet.
"""

import importlib
import pkgutil

from imbi.common.db.etl import mapping
from imbi.common.db.etl.mappings import _pending


def discover() -> dict[str, mapping.Mapping]:
    """Import the mapping modules and return their mappings by table."""
    found: dict[str, mapping.Mapping] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=_name):
        if info.name.startswith('_'):
            continue
        module = importlib.import_module(f'{__name__}.{info.name}')
        value: object = getattr(module, 'MAPPING', None)
        if not isinstance(value, mapping.Mapping):
            raise mapping.EtlError(
                f'{module.__name__} has no MAPPING that satisfies Mapping'
            )
        if value.table != info.name:
            raise mapping.EtlError(
                f'{module.__name__} maps table {value.table!r};'
                f' the module name must be the table name'
            )
        found[value.table] = value
    return found


def pending() -> tuple[str, ...]:
    """Return the tables that have no mapping module yet."""
    return tuple(
        sorted(
            table for tables in _pending.PENDING.values() for table in tables
        )
    )


def _name(info: pkgutil.ModuleInfo) -> str:
    return info.name
