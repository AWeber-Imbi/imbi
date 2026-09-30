"""The one-time load of the relational tables from the AGE graph.

``mapping`` has the contract of a mapping module, ``mappings`` the
modules, ``runner.run()`` the load, ``reconcile.reconcile()`` the
report, and ``cli`` the ``imbi-common etl`` commands. See ``mapping``
for how to write a mapping.
"""

from imbi.common.db.etl.graph import read_edges, read_label
from imbi.common.db.etl.ids import derive_id
from imbi.common.db.etl.mapping import (
    Cardinality,
    Change,
    Context,
    EtlError,
    Event,
    Expected,
    Mapping,
    Row,
    Skip,
)

__all__ = [
    'Cardinality',
    'Change',
    'Context',
    'EtlError',
    'Event',
    'Expected',
    'Mapping',
    'Row',
    'Skip',
    'derive_id',
    'read_edges',
    'read_label',
]
