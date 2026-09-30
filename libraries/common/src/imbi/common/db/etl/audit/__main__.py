"""``python -m imbi.common.db.etl.audit audit``, until the ``imbi-common``
command registers ``etl audit``."""

from imbi.common.db.etl.audit import cli

cli.app()
