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
    local env_test="$repo/.env.test" line url
    test -n "${PGHOST:-}" && return 0
    test -f "$env_test" || return 0
    if ! line=$(grep -m1 '^POSTGRES_URL=' "$env_test"); then
        echo "$env_test has no POSTGRES_URL line. Run" \
             "\`moon run root:services\`, or set PGHOST." >&2
        exit 2
    fi
    url=$(echo "$line" | cut -d= -f2- | tr -d '"\r')
    if ! [[ $url =~ ^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+):([0-9]+)/ ]]
    then
        echo "cannot read POSTGRES_URL in $env_test: $url" >&2
        exit 2
    fi
    export PGUSER="${BASH_REMATCH[1]}"
    export PGPASSWORD="${BASH_REMATCH[3]}"
    export PGHOST="${BASH_REMATCH[4]}"
    export PGPORT="${BASH_REMATCH[5]}"
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

# Pass when the output has a plan line 1..N, N test lines, and no
# failed test.
tap_passed() {
    local planned ran
    planned=$(sed -nE 's/^1\.\.([0-9]+)$/\1/p' "$1" | head -n 1)
    ran=$(grep -cE '^(not )?ok [0-9]+' "$1" || true)
    if grep -qE '^not ok' "$1"; then
        return 1
    fi
    if test -z "$planned" || test "$planned" != "$ran"; then
        echo "planned ${planned:-no} tests, ran $ran" >&2
        return 1
    fi
}

# check drops only the databases that it made itself. It marks each one
# with this comment, and refuses a name that another database has.
MARKER='imbi schemata/scripts/schema.sh check scratch database'

# Print absent, ours (the database has the marker), or foreign.
database_state() {
    psql_run -d postgres -At -v name="$1" -v marker="$MARKER" <<'SQL'
SELECT coalesce(
         (SELECT CASE
                   WHEN shobj_description(oid, 'pg_database') = :'marker'
                     THEN 'ours'
                   ELSE 'foreign'
                 END
            FROM pg_database
           WHERE datname = :'name'),
         'absent')
SQL
}

drop_scratch_database() {
    if test "$(database_state "$1")" = 'ours'; then
        psql_run -d postgres -c \
            "DROP DATABASE $(quote_ident "$1") WITH (FORCE)"
    fi
}

# create_scratch_database NAME [TEMPLATE]
create_scratch_database() {
    local qname template=''
    case "$(database_state "$1")" in
        foreign)
            echo "Database $1 exists, and schema.sh check did not make" \
                 "it. check does not drop it; give another name." >&2
            exit 2
            ;;
        ours)
            drop_scratch_database "$1"
            ;;
    esac
    qname=$(quote_ident "$1")
    if test -n "${2:-}"; then
        template=" TEMPLATE $(quote_ident "$2")"
    fi
    psql_run -d postgres -c "CREATE DATABASE $qname$template"
    cleanup_databases+=("$1")
    echo "COMMENT ON DATABASE $qname IS :'marker'" \
        | psql_run -d postgres -v marker="$MARKER"
}

check() {
    local db="$1" test_db tests=0 failed=0 file files=()
    if test "$db" = 'imbi'; then
        echo 'check makes a new database; give a name other than imbi' >&2
        exit 2
    fi
    for file in "$project"/tests/test_*.sql; do
        test -e "$file" && files+=("$file")
    done
    if test "${#files[@]}" -eq 0; then
        echo "no test files in $project/tests (test_*.sql)" >&2
        exit 1
    fi

    echo "== build"
    "$pgl" build "$project" "$work/schema.dump"

    # With no password variable, create-roles.sql must stop before it
    # creates a role, with an exit status that is not 0, also when the
    # caller does not set ON_ERROR_STOP.
    echo "== create-roles.sql without the password variables"
    if psql -X -q -d postgres -f "$scripts/create-roles.sql" \
        > "$work/roles.out" 2>&1; then
        cat "$work/roles.out" >&2
        echo 'create-roles.sql exited 0 with no password variables' >&2
        exit 1
    fi
    echo 'create-roles.sql stops with no password variables'

    echo "== deploy into a new database $db"
    create_scratch_database "$db"
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

    test_db="${db}_test"
    for file in "${files[@]}"; do
        tests=$((tests + 1))
        echo "== $(basename "$file")"
        create_scratch_database "$test_db" "$db"
        psql_run -d "$test_db" \
            -c 'CREATE SCHEMA tap' \
            -c 'CREATE EXTENSION pgtap SCHEMA tap' \
            -c 'GRANT USAGE ON SCHEMA tap TO PUBLIC'
        # The tests roll back transactions, and a rollback also removes
        # the pgTAP state of the tests in it, so finish() cannot count
        # them. This reads the TAP output instead, as pg_prove does.
        # Only the TAP lines are shown; errors go to stderr.
        if ! psql_run -At -d "$test_db" -f "$file" > "$work/tap.out" \
           || ! tap_passed "$work/tap.out"; then
            failed=$((failed + 1))
            echo "FAILED: $(basename "$file")" >&2
        fi
        grep -E '^(ok|not ok|#|1\.\.)' "$work/tap.out" || true
        drop_scratch_database "$test_db"
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
        drop_scratch_database "$db" > /dev/null 2>&1 || true
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
