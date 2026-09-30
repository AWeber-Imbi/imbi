#!/usr/bin/env bash
# root:cutover-check: test the DDL steps of the cutover runbook
# (docs/architecture/age-cutover-runbook.md) on an AGE-era fixture.
#
#   schemata/cutover/cutover-check.sh
#
# The sequence:
#
#   1. Build the AGE-era fixture (fixture/age-era.sql). freeze.sql
#      refuses a wrong role, then blocks a stand-in AGE-era login and
#      ends its session; LOGIN again (rollback step 3) lets it connect.
#   2. rollback.sql on the fixture changes nothing.
#   3. pre-deploy.sql, then rollback.sql: the fixture is back.
#   4. First attempt: pre-deploy.sql; the deploy plan has no destructive
#      statement; the plan, set-owners.sql, and checks.sql apply in one
#      transaction; a second deploy equals the allowlist.
#   5. checks.sql fails on each known defect. rls-probe.sql passes on two
#      organizations and fails with a policy that leaks.
#   6. rollback.sql twice: public.embeddings has its rows, indexes, and
#      owner again, and the AGE-era search query uses the HNSW index.
#   7. Second attempt: the same checks as step 4.
#
# The graph and the scheduler schema must not change in any step.
#
# Safety: the script drops and creates a database and login roles. It
# refuses to run unless CUTOVER_CHECK_ALLOW=1, PGHOST is a loopback
# address or a socket, and the login is not imbi_operator (the operator
# login of the cutover runbook). Never run it in the shell of a cutover:
# there, a loopback PGHOST is a port-forward to production.
#
# Connection: the libpq variables PGHOST, PGPORT, PGUSER, and
# PGPASSWORD (a superuser). When PGHOST is not set, the script reads
# POSTGRES_URL from .env.test, which `moon run root:services` writes, as
# schemata/scripts/schema.sh does. The roles of
# schemata/scripts/create-roles.sql must exist. Settings:
#
#   CUTOVER_CHECK_ALLOW  must be 1. Without it, the script does nothing.
#                Never set it in the shell of a cutover.
#   CUTOVER_DB   the scratch database (default cutover_check). The
#                script creates it with the comment "root:cutover-check
#                fixture", and it drops or reuses only a database that has
#                that comment. When it is the database that
#                cron.database_name names, the fixture has pg_cron.
#   PGLIFECYCLE  the pglifecycle binary (default: the pinned build of
#                schemata/scripts/install-pglifecycle.sh).
#   WORK_DIR     where the plans go (default a new temporary directory).
#   KEEP_DB      set to 1 to keep the database at the end.
#   SET_OWNERS   the owners script (default schemata/scripts/set-owners.sql).
#   ALLOWLIST    the second-deploy allowlist (default
#                schemata/tests/second-deploy-allowlist.sql).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SCHEMATA=$(cd "$HERE/.." && pwd)
REPO=$(dirname "$SCHEMATA")
DB=${CUTOVER_DB:-cutover_check}
WORK=${WORK_DIR:-$(mktemp -d)}
SET_OWNERS=${SET_OWNERS:-$SCHEMATA/scripts/set-owners.sql}
ALLOWLIST=${ALLOWLIST:-$SCHEMATA/tests/second-deploy-allowlist.sql}
# The deploy flags of the cutover (runbook step 6).
FLAGS=(-N imbi -N ag_catalog -N scheduler -N legacy
       --exclude-extension age --exclude-extension pg_cron)

mkdir -p "$WORK"

# The same connection rule as schemata/scripts/schema.sh.
if [ -z "${PGHOST:-}" ] && [ -f "$REPO/.env.test" ]; then
  url=$(grep -m1 '^POSTGRES_URL=' "$REPO/.env.test" | cut -d= -f2- \
        | tr -d '"\r')
  if [[ $url =~ ^postgresql://([^:@/]+)(:([^@/]*))?@([^:/]+):([0-9]+)/ ]]
  then
    export PGUSER="${BASH_REMATCH[1]}" PGPASSWORD="${BASH_REMATCH[3]}"
    export PGHOST="${BASH_REMATCH[4]}" PGPORT="${BASH_REMATCH[5]}"
  fi
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# SQL on the maintenance database postgres.
qp() {
  psql -d postgres -X -At -v ON_ERROR_STOP=1 -c "$1"
}

MARKER='root:cutover-check fixture'
STAND_INS=(age_member age_mid age_other age_app)

[ "${CUTOVER_CHECK_ALLOW:-}" = 1 ] \
  || fail 'set CUTOVER_CHECK_ALLOW=1 to run (never in a cutover shell)'
case "${PGHOST:-}" in
  ''|127.0.0.1|localhost|::1|/*) ;;
  *) fail "PGHOST=$PGHOST is not a loopback address or a socket" ;;
esac
[[ $DB =~ ^[a-z_][a-z0-9_]*$ ]] || fail "CUTOVER_DB=$DB is not a plain name"
[ "$(qp 'SELECT current_user')" != imbi_operator ] \
  || fail 'the login is imbi_operator: this is a cutover shell'

PGLIFECYCLE=$("$SCHEMATA/scripts/install-pglifecycle.sh")
ROLE_PASSWORD=$(openssl rand -hex 16)

# Drop the database only when it has the marker.
drop_fixture_db() {
  [ "$(qp "SELECT count(*) FROM pg_database WHERE datname = '$DB'")" = 1 ] \
    || return 0
  [ "$(qp "SELECT coalesce(shobj_description(oid, 'pg_database'), '')
             FROM pg_database WHERE datname = '$DB'")" = "$MARKER" ] \
    || fail "database $DB exists without the comment '$MARKER'; not dropped"
  qp "DROP DATABASE $DB WITH (FORCE)" > /dev/null
}

# The stand-in roles of check_freeze are global. Drop only the ones with
# the marker, at the start and on any exit.
drop_stand_ins() {
  local role name
  for role in "${STAND_INS[@]}"; do
    name=${DB}_$role
    [ "$(qp "SELECT count(*) FROM pg_roles WHERE rolname = '$name'")" = 1 ] \
      || continue
    if [ "$(qp "SELECT coalesce(shobj_description(oid, 'pg_authid'), '')
                  FROM pg_roles WHERE rolname = '$name'")" != "$MARKER" ]; then
      echo "role $name exists without the comment '$MARKER'; not dropped" >&2
      return 1
    fi
    qp "DROP ROLE $name" > /dev/null
  done
}

# Make a stand-in role with the marker and the random password.
make_role() {
  qp "CREATE ROLE $1 $2 PASSWORD '$ROLE_PASSWORD'" > /dev/null
  qp "COMMENT ON ROLE $1 IS '$MARKER'" > /dev/null
}

cleanup() {
  drop_stand_ins > /dev/null 2>&1 || true
}
trap cleanup EXIT
drop_stand_ins || fail 'a stand-in role name is in use'

q() {
  psql -d "$DB" -X -At -v ON_ERROR_STOP=1 -c "$1"
}

run_sql() {
  psql -d "$DB" -X -q -v ON_ERROR_STOP=1 -1 "$@" > /dev/null
}

expect() {
  local name=$1 actual=$2 expected=$3
  if [ "$actual" != "$expected" ]; then
    fail "$name: got '$actual', expected '$expected'"
  fi
  echo "  ok: $name = $expected"
}

# The statements of a plan, without comments and blank lines.
statements() {
  grep -vE '^[[:space:]]*(--|$)' "$1" || true
}

deploy() {
  "$PGLIFECYCLE" deploy -d "$DB" --error-file "$WORK/errors.log" \
    "${FLAGS[@]}" "$@" "$SCHEMATA" > "$WORK/deploy.log" 2>&1 \
    || { cat "$WORK/deploy.log" >&2; fail "pglifecycle deploy $*"; }
}

# The state that no step may change: the graph and the scheduler.
untouched_state() {
  q "SELECT (SELECT count(*) FROM ag_catalog.ag_graph WHERE name = 'imbi')
            || ' ' || (SELECT count(*) FROM imbi.\"Project\")
            || ' ' || (to_regclass('scheduler.jobs') IS NOT NULL)"
}

# The AGE-era state: the legacy table in public with its rows, indexes,
# and owner, vector in ag_catalog, and no schema legacy.
check_age_era() {
  expect 'legacy rows in public.embeddings' \
    "$(q 'SELECT count(*) FROM public.embeddings')" 2
  expect 'public.embeddings indexes' \
    "$(q "SELECT string_agg(indexname, ' ' ORDER BY indexname)
            FROM pg_indexes
           WHERE schemaname = 'public' AND tablename = 'embeddings'")" \
    'embeddings_node_idx embeddings_pkey embeddings_text_hnsw_idx'
  expect 'public.embeddings has no organization_id' \
    "$(q "SELECT count(*) FROM pg_attribute
           WHERE attrelid = 'public.embeddings'::regclass
             AND attname = 'organization_id'")" 0
  expect 'public.embeddings owner' \
    "$(q "SELECT tableowner FROM pg_tables
           WHERE schemaname = 'public' AND tablename = 'embeddings'")" \
    "$LEGACY_OWNER"
  expect 'vector schema' \
    "$(q "SELECT extnamespace::regnamespace FROM pg_extension
           WHERE extname = 'vector'")" ag_catalog
  expect 'embedding_distance in public' \
    "$(q "SELECT string_agg(pronamespace::regnamespace::text, ' ')
            FROM pg_proc WHERE proname = 'embedding_distance'")" public
  expect 'schema legacy exists' \
    "$(q "SELECT to_regnamespace('legacy') IS NOT NULL")" f
  expect 'graph and scheduler' "$(untouched_state)" "$UNTOUCHED"
}

# The AGE-era search query (graph/client.py) with the search_path of
# the AGE-era pool. It must use the HNSW index and return rows.
# shellcheck disable=SC2016 # "$user" is part of the SQL, not a variable
check_age_era_search() {
  local vec="array_fill(0.1::real, ARRAY[384])::vector(384)"
  local search="SELECT node_id FROM public.embeddings
                 WHERE model_name = 'text'
                 ORDER BY (embedding::vector(384)) <=> ($vec) LIMIT 1"
  expect 'AGE-era search uses the HNSW index' \
    "$(psql -d "$DB" -X -At -v ON_ERROR_STOP=1 \
         -c 'SET search_path = ag_catalog, "$user", public' \
         -c 'SET enable_seqscan = off' \
         -c "EXPLAIN $search" | grep -c embeddings_text_hnsw_idx)" 1
  expect 'AGE-era search returns a row' \
    "$(psql -d "$DB" -X -q -At -v ON_ERROR_STOP=1 \
         -c 'SET search_path = ag_catalog, "$user", public' \
         -c "SELECT count(*) FROM ($search) AS s")" 1
}

# Runbook steps 5 and 6, and the checks of the plan.
attempt() {
  local name=$1
  echo "== $name: pre-deploy.sql"
  run_sql -f "$HERE/pre-deploy.sql"
  expect 'legacy rows' "$(q 'SELECT count(*) FROM legacy.embeddings')" 2
  expect 'embedding_distance moved to legacy' \
    "$(q "SELECT string_agg(pronamespace::regnamespace::text, ' ')
            FROM pg_proc WHERE proname = 'embedding_distance'")" legacy

  echo "== $name: deploy plan"
  deploy -o "$WORK/$name.sql"
  deploy --allow-drop -o "$WORK/$name-allow-drop.sql"
  expect 'plan header' \
    "$(grep -m1 '^-- destructive statements:' "$WORK/$name.sql")" \
    '-- destructive statements: none'
  if ! diff <(statements "$WORK/$name.sql") \
            <(statements "$WORK/$name-allow-drop.sql") > /dev/null; then
    fail "$name: the plan with --allow-drop has more statements"
  fi
  echo '  ok: --allow-drop adds no statement'
  if statements "$WORK/$name.sql" \
       | grep -qiE '^[[:space:]]*(DROP|TRUNCATE)[[:space:]]|[[:space:]]DROP[[:space:]]+(COLUMN|CONSTRAINT)[[:space:]]'; then
    fail "$name: the plan has a DROP or TRUNCATE statement"
  fi
  echo '  ok: no DROP or TRUNCATE in the plan'
  echo "  plan statements: $(statements "$WORK/$name.sql" | wc -l | tr -d ' ')"

  echo "== $name: apply plan, set-owners.sql, checks.sql in one transaction"
  run_sql -f "$WORK/$name.sql" -f "$SET_OWNERS" -f "$HERE/checks.sql"
  expect 'tables in public' \
    "$(q "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")" \
    "$(find "$SCHEMATA/tables/public" -name '*.yaml' | wc -l | tr -d ' ')"
  expect 'legacy rows' "$(q 'SELECT count(*) FROM legacy.embeddings')" 2
  expect 'graph and scheduler' "$(untouched_state)" "$UNTOUCHED"

  echo "== $name: second deploy equals the allowlist"
  deploy --allow-drop -o "$WORK/$name-second.sql"
  if ! diff <(statements "$ALLOWLIST") \
            <(statements "$WORK/$name-second.sql"); then
    fail "$name: the second deploy differs from $ALLOWLIST"
  fi
  echo '  ok: second deploy = allowlist'
}

# Open a session of role $1 that waits. SESSION_PID is its job.
open_session() {
  PGPASSWORD="$ROLE_PASSWORD" psql -d "$DB" -U "$1" -X -q \
    -c 'SELECT pg_sleep(600)' > /dev/null 2>&1 &
  SESSION_PID=$!
  local _
  for _ in $(seq 1 50); do
    [ "$(q "SELECT count(*) FROM pg_stat_activity
             WHERE usename = '$1'")" = 1 ] && break
    sleep 0.2
  done
}

# Runbook step 4 (freeze.sql) and rollback step 3 (LOGIN again), with a
# stand-in AGE-era login that has an open session.
check_freeze() {
  echo '== freeze.sql'
  local login=${DB}_age_app member=${DB}_age_member mid=${DB}_age_mid
  local other=${DB}_age_other session other_session
  make_role "$login" LOGIN
  make_role "$other" LOGIN
  open_session "$login"
  session=$SESSION_PID
  expect 'open AGE-era session' \
    "$(q "SELECT count(*) FROM pg_stat_activity WHERE usename = '$login'")" 1

  freeze() {
    psql -d "$DB" -X -q -v ON_ERROR_STOP=1 -v age_login="$1" \
      -f "$HERE/freeze.sql" > "$WORK/freeze.log" 2>&1
  }
  if freeze "$(q 'SELECT current_user')"; then
    fail 'freeze.sql accepted the operator role'
  fi
  grep -q 'is the operator role' "$WORK/freeze.log" \
    || fail "freeze.sql failed for a different reason: $(cat "$WORK/freeze.log")"
  echo '  ok: freeze.sql refuses the operator role'
  if freeze imbi_app; then
    fail 'freeze.sql accepted imbi_app'
  fi
  grep -q 'is a role of the relational schema' "$WORK/freeze.log" \
    || fail "freeze.sql failed for a different reason: $(cat "$WORK/freeze.log")"
  echo '  ok: freeze.sql refuses imbi_app'
  make_role "$member" "LOGIN IN ROLE $login"
  if freeze "$login"; then
    fail 'freeze.sql accepted a role with a login member'
  fi
  grep -q 'login roles are members' "$WORK/freeze.log" \
    || fail "freeze.sql failed for a different reason: $(cat "$WORK/freeze.log")"
  echo '  ok: freeze.sql refuses a role with a direct login member'
  q "DROP ROLE $member" > /dev/null
  make_role "$mid" "NOLOGIN IN ROLE $login"
  make_role "$member" "LOGIN IN ROLE $mid"
  if freeze "$login"; then
    fail 'freeze.sql accepted a role with an indirect login member'
  fi
  grep -q 'login roles are members' "$WORK/freeze.log" \
    || fail "freeze.sql failed for a different reason: $(cat "$WORK/freeze.log")"
  echo '  ok: freeze.sql refuses a role with an indirect login member'
  q "DROP ROLE $member" > /dev/null
  q "DROP ROLE $mid" > /dev/null
  expect 'the refusals changed nothing' \
    "$(q "SELECT rolcanlogin FROM pg_roles WHERE rolname = '$login'")" t

  open_session "$other"
  other_session=$SESSION_PID
  if freeze "$login"; then
    fail 'freeze.sql passed with another client connected'
  fi
  grep -q 'other sessions are connected' "$WORK/freeze.log" \
    || fail 'freeze.sql failed for a different reason'
  echo '  ok: freeze.sql stops while another client is connected'
  if wait "$session"; then
    fail 'the AGE-era session was not ended'
  fi
  echo '  ok: the AGE-era session ended'
  expect 'AGE-era login' \
    "$(q "SELECT rolcanlogin FROM pg_roles WHERE rolname = '$login'")" f
  if PGPASSWORD="$ROLE_PASSWORD" psql -d "$DB" -U "$login" -X -c 'SELECT 1' \
       > /dev/null 2>&1; then
    fail 'the AGE-era login can still connect'
  fi
  echo '  ok: the AGE-era login cannot connect'
  q "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity
      WHERE usename = '$other'" > /dev/null
  wait "$other_session" || true
  freeze "$login" || fail 'freeze.sql failed'
  echo '  ok: freeze.sql passes when no other client is connected'
  freeze "$login" || fail 'a second run of freeze.sql failed'
  echo '  ok: a second run passes'

  echo '== rollback step 3: LOGIN again'
  q "ALTER ROLE $login LOGIN" > /dev/null
  expect 'the AGE-era login connects' \
    "$(PGPASSWORD="$ROLE_PASSWORD" psql -d "$DB" -U "$login" -X -At \
         -c 'SELECT 1')" 1
  q "DROP ROLE $login" > /dev/null
  q "DROP ROLE $other" > /dev/null
}

# Runbook step 9 (rls-probe.sql) on a small data set of two
# organizations. The probe passes, and fails with a policy that leaks.
check_rls_probe() {
  echo '== rls-probe.sql'
  run_sql -c "INSERT INTO public.tenants (id, name, slug)
                   VALUES ('t1', 'Tenant', 'tenant')" \
          -c "INSERT INTO public.organizations (id, tenant_id, name, slug)
                   VALUES ('o1', 't1', 'One', 'one'),
                          ('o2', 't1', 'Two', 'two')" \
          -c "INSERT INTO public.tags (id, organization_id, name, slug)
                   VALUES ('g1', 'o1', 'A', 'a'), ('g2', 'o2', 'B', 'b')"
  probe() {
    psql -d "$DB" -X -q -v ON_ERROR_STOP=1 -v org_id=o1 "$@" \
      -f "$HERE/rls-probe.sql" > "$WORK/probe.log" 2>&1
  }
  probe || { cat "$WORK/probe.log" >&2; fail 'rls-probe.sql failed'; }
  echo "  ok: $(grep -o 'rls probe: .*' "$WORK/probe.log")"
  if probe -c 'BEGIN' \
       -c 'CREATE POLICY cutover_leak ON public.tags USING (true)'; then
    fail 'rls-probe.sql passed with a policy that leaks'
  fi
  grep -q 'rls probe:' "$WORK/probe.log" \
    || fail "rls-probe.sql failed for another reason: $(cat "$WORK/probe.log")"
  echo '  ok: rls-probe.sql fails with a policy that leaks'
  expect 'the probe changed nothing' \
    "$(q "SELECT count(*) FROM pg_policies WHERE policyname = 'cutover_leak'")" 0
  run_sql -c "DELETE FROM public.tags" -c "DELETE FROM public.organizations" \
          -c "DELETE FROM public.tenants"
}

# checks.sql must fail on each of these defects.
check_negative() {
  echo '== checks.sql fails on known defects'
  local defects=(
    'GRANT SELECT ON public.tags TO PUBLIC'
    'ALTER TABLE public.tags OWNER TO imbi_app'
    'ALTER TABLE public.tags NO FORCE ROW LEVEL SECURITY'
    'ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY'
    'GRANT UPDATE ON public.components TO imbi_app'
    'GRANT EXECUTE ON FUNCTION public.principal_teams() TO PUBLIC'
    'ALTER FUNCTION public.principal_teams() OWNER TO imbi_owner'
    'ALTER FUNCTION public.delete_embeddings() OWNER TO imbi_definer'
    'ALTER EXTENSION vector SET SCHEMA ag_catalog'
    'ALTER ROLE imbi_app BYPASSRLS'
    'GRANT imbi_trigger TO imbi_maintenance'
    'CREATE TABLE public.extra (id integer)'
    'ALTER FUNCTION public.principal_teams() RESET search_path'
    'ALTER TABLE public.tags ADD CONSTRAINT x CHECK (true) NOT VALID'
    'DROP TABLE legacy.embeddings'
  )
  local defect
  for defect in "${defects[@]}"; do
    if psql -d "$DB" -X -q -v ON_ERROR_STOP=1 -1 -c "$defect" \
         -f "$HERE/checks.sql" > "$WORK/negative.log" 2>&1; then
      fail "checks.sql passed with: $defect"
    fi
    grep -q 'cutover check:' "$WORK/negative.log" \
      || fail "checks.sql failed for another reason with: $defect: $(cat "$WORK/negative.log")"
    echo "  ok: fails with: $defect"
  done
}

for file in "$SET_OWNERS" "$ALLOWLIST"; do
  [ -f "$file" ] || fail "$file does not exist"
done
echo "pglifecycle: $("$PGLIFECYCLE" --version)"
echo "pglifecycle sha256: $(shasum -a 256 "$PGLIFECYCLE" | cut -d' ' -f1)"
echo "work dir: $WORK"

echo "== fixture: $DB"
drop_fixture_db
qp "CREATE DATABASE $DB" > /dev/null
qp "COMMENT ON DATABASE $DB IS '$MARKER'" > /dev/null
run_sql -f "$HERE/fixture/age-era.sql"
UNTOUCHED=$(untouched_state)
LEGACY_OWNER=$(q "SELECT tableowner FROM pg_tables
                   WHERE schemaname = 'public'
                     AND tablename = 'embeddings'")
expect 'graph and scheduler' "$UNTOUCHED" '1 2 true'
echo "  pg_cron in the fixture: $(q "SELECT count(*) FROM pg_extension
                                      WHERE extname = 'pg_cron'")"
check_age_era
check_age_era_search
check_freeze

echo '== rollback.sql on the AGE-era database changes nothing'
run_sql -f "$HERE/rollback.sql"
check_age_era

echo '== pre-deploy.sql, then rollback.sql (failure in step 6)'
run_sql -f "$HERE/pre-deploy.sql"
expect 'vector schema recorded' \
  "$(q 'SELECT vector_schema FROM legacy.cutover_state')" ag_catalog
run_sql -f "$HERE/rollback.sql"
check_age_era
expect 'rollback.sql refuses a legacy table without cutover_state' \
  "$( (psql -d "$DB" -X -q -v ON_ERROR_STOP=1 -1 -f "$HERE/pre-deploy.sql" \
         -c 'DROP TABLE legacy.cutover_state' -f "$HERE/rollback.sql" \
         2>&1 || true) | grep -c 'cutover_state is missing')" 1
check_age_era

attempt first
check_negative
check_rls_probe

echo '== rollback.sql after the first attempt, twice'
run_sql -f "$HERE/rollback.sql"
check_age_era
run_sql -f "$HERE/rollback.sql"
check_age_era
check_age_era_search
expect 'relational tables stay' \
  "$(q "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")" \
  "$(find "$SCHEMATA/tables/public" -name '*.yaml' | wc -l | tr -d ' ')"
expect 'pre-deploy.sql refuses a second run without rollback' \
  "$( (run_sql -f "$HERE/pre-deploy.sql" -f "$HERE/pre-deploy.sql" \
       2>&1 || true) | grep -c 'schema legacy exists')" 1

attempt second

if [ "${KEEP_DB:-0}" != 1 ]; then
  drop_fixture_db
fi
echo 'PASS: cutover-check'
