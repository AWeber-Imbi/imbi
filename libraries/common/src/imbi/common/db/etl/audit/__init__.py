"""Pre-migration audit of the AGE graph (plan WP1.9).

``audit_command`` is the ``imbi-common etl audit`` command.
"""

from imbi.common.db.etl.audit.cli import audit_command

__all__ = ['audit_command']
