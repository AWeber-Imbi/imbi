#!/bin/sh
#
# Run create-roles.sql in the postgres container of compose.ci.yaml.
# The image runs this script from /docker-entrypoint-initdb.d when it
# makes a new cluster. `moon run root:services` runs it again with
# `docker compose exec`, for a container that existed before the roles.
# The passwords come from the IMBI_*_PASSWORD variables of the service.

set -e

psql -X -q -v ON_ERROR_STOP=1 \
    --username "${POSTGRES_USER:-postgres}" \
    --dbname "${POSTGRES_DB:-postgres}" \
    -v app_password="$IMBI_APP_PASSWORD" \
    -v admin_password="$IMBI_ADMIN_PASSWORD" \
    -v maintenance_password="$IMBI_MAINTENANCE_PASSWORD" \
    -f /schemata/scripts/create-roles.sql
