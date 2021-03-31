# PostgreSQL DDL

Sub-project for managing the DDL for Imbi

Extending or Editing
--------------------
The [MANIFEST](MANIFEST) file contains all of the files that are used to construct
the DDL that is used for the analytics system. It should be edited for any files
that are added or removed. The files are ordered properly for dependency in the
MANIFEST file and care should be taken to ensure it stays that way.

pg_cron
-------
For the recording of Namespace KPIs into the `v1.namespace_kpi_history` table
the [pg_cron](https://github.com/citusdata/pg_cron) extension is intended to be 
used.

Testing
-------
Testing requires [pgTap](https://pgtap.org)  tests. The base Docker image used
for testing has all the pgTap requirements, already installed.

To run all the tests in the tests subdirectory, just run ``make test`` in the 
top-level project directory.
