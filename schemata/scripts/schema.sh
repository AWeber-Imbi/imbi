#!/usr/bin/env bash
#
# Run pglifecycle for the schemata/ project. The moon tasks
# root:schema-plan, root:schema-apply and root:schema-check call this
# script.
#
# Usage:
#   schemata/scripts/schema.sh plan DATABASE    # print the deploy DDL
#   schemata/scripts/schema.sh apply DATABASE   # deploy, check owners
#   schemata/scripts/schema.sh check [DATABASE] # the full schema check
#
# check builds the project, applies it to a new database (default
# imbi_schema_check), compares a second deploy with
# schemata/tests/second-deploy-allowlist.sql, runs each
# schemata/tests/test_*.sql pgTAP file in its own copy of that database,
# and drops the databases.
#
# The server comes from the libpq variables PGHOST, PGPORT, PGUSER and
# PGPASSWORD. When PGHOST is not set, the script reads POSTGRES_URL from
# .env.test, which `moon run root:services` writes. The roles must exist
# (schemata/scripts/create-roles.sql).
#
# Do not apply the project to a database where an AGE-era app has run
# (implementation plan rule 0.10). apply refuses a database that has the
# legacy public.embeddings table.

set -euo pipefail

scripts=$(cd "$(dirname "$0")" && pwd)
project=$(dirname "$scripts")
repo=$(dirname "$project")

flags=(
    -N imbi -N ag_catalog -N scheduler
    --exclude-extension age --exclude-extension pg_cron
)

usage() {
    echo "usage: $0 plan DATABASE | apply DATABASE | check [DATABASE]" >&2
    exit 2
}

connect_from_env_test() {
    local url
    test -n "${PGHOST:-}" && return 0
    test -f "$repo/.env.test" || return 0
    url=$(grep -m1 '^POSTGRES_URL=' "$repo/.env.test" | cut -d= -f2- \
          | tr -d '"\r')
    if [[ $url =~ ^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+):([0-9]+)/ ]]
    then
        export PGUSER="${BASH_REMATCH[1]}"
        export PGPASSWORD="${BASH_REMATCH[3]}"
        export PGHOST="${BASH_REMATCH[4]}"
        export PGPORT="${BASH_REMATCH[5]}"
    fi
}

psql_run() {
    psql -X -q -v ON_ERROR_STOP=1 "$@"
}

quote_ident() {
    echo "SELECT quote_ident(:'name')" | psql_run -d postgres -At -v name="$1"
}

deploy_plan() {
    "$pgl" deploy -d "$1" --error-file "$work/errors.log" "${flags[@]}" \
        "$project"
}

deploy_apply() {
    local legacy
    legacy=$(psql_run -d "$1" -Atc \
        "SELECT to_regclass('public.embeddings') IS NOT NULL
            AND to_regclass('public.tenants') IS NULL")
    if test "$legacy" = 't'; then
        echo "$1 has the legacy public.embeddings table of the AGE-era" \
             "app. Do not apply the project to it (plan rule 0.10)." >&2
        exit 1
    fi
    "$pgl" deploy -d "$1" --apply --error-file "$work/errors.log" \
        "${flags[@]}" "$project"
    psql_run -d "$1" -f "$scripts/set-owners.sql"
}

# Keep only the statement lines: no comments and no blank lines.
statements() {
    grep -vE '^[[:space:]]*(--.*)?$' "$1" || true
}

drop_database() {
    psql_run -d postgres -c \
        "DROP DATABASE IF EXISTS $(quote_ident "$1") WITH (FORCE)"
}

check() {
    local db="$1" qdb test_db tests=0 failed=0
    if test "$db" = 'imbi'; then
        echo 'check makes a new database; give a name other than imbi' >&2
        exit 2
    fi
    qdb=$(quote_ident "$db")

    echo "== build"
    "$pgl" build "$project" "$work/schema.dump"

    echo "== deploy into a new database $db"
    cleanup_databases=("$db")
    drop_database "$db"
    psql_run -d postgres -c "CREATE DATABASE $qdb"
    deploy_apply "$db"

    echo "== second deploy"
    "$pgl" deploy -d "$db" --allow-drop -o "$work/second.sql" \
        --error-file "$work/errors.log" "${flags[@]}" "$project"
    if ! diff -u \
        <(statements "$project/tests/second-deploy-allowlist.sql") \
        <(statements "$work/second.sql"); then
        echo 'The second deploy is not the same as' \
             'tests/second-deploy-allowlist.sql (diff above: + is the' \
             'second deploy).' >&2
        exit 1
    fi
    echo 'second deploy has only the allowlisted statements'

    for file in "$project"/tests/test_*.sql; do
        test -e "$file" || continue
        tests=$((tests + 1))
        test_db="${db}_test"
        echo "== $(basename "$file")"
        cleanup_databases+=("$test_db")
        drop_database "$test_db"
        psql_run -d postgres -c \
            "CREATE DATABASE $(quote_ident "$test_db") TEMPLATE $qdb"
        psql_run -d "$test_db" \
            -c 'CREATE SCHEMA tap' \
            -c 'CREATE EXTENSION pgtap SCHEMA tap' \
            -c 'GRANT USAGE ON SCHEMA tap TO PUBLIC'
        if ! psql_run -At -d "$test_db" -f "$file"; then
            failed=$((failed + 1))
            echo "FAILED: $(basename "$file")" >&2
        fi
        drop_database "$test_db"
    done
    if test "$failed" -gt 0; then
        echo "$failed of $tests test files failed" >&2
        exit 1
    fi
    echo "schema check passed: $tests test files"
}

cleanup() {
    local db
    for db in ${cleanup_databases[@]+"${cleanup_databases[@]}"}; do
        drop_database "$db" > /dev/null 2>&1 || true
    done
    rm -rf "$work"
}

command="${1:-}"
shift || true
cleanup_databases=()
work=$(mktemp -d)
trap cleanup EXIT

connect_from_env_test
pgl=$("$scripts/install-pglifecycle.sh")

case "$command" in
    plan)
        test $# -eq 1 || usage
        deploy_plan "$1"
        ;;
    apply)
        test $# -eq 1 || usage
        deploy_apply "$1"
        ;;
    check)
        test $# -le 1 || usage
        check "${1:-${SCHEMA_CHECK_DB:-imbi_schema_check}}"
        ;;
    *)
        usage
        ;;
esac
