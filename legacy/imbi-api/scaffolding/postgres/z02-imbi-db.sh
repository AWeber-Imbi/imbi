#!/usr/bin/env sh
set -e
createdb imbi
for f in /docker-entrypoint-initdb.d/*.sql
do
	psql -d imbi -f "$f"
done
