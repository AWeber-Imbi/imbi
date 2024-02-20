#!/usr/bin/env sh
set -e
createdb imbi
psql -d imbi -f /docker-entrypoint-initdb.d/ddl.sql
psql -d imbi -f /docker-entrypoint-initdb.d/z01-data.sql
