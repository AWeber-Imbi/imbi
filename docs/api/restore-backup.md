# How to Restore an Imbi Database Backup

Take a `pg_dump` backup of the Imbi PostgreSQL database and restore it,
including the Apache AGE graph. For ClickHouse, see
[Operations: Backups](../deployment/operations.md#backups).

## Prerequisites

- The target PostgreSQL server has the `age`, `pg_cron`, and `vector`
  extensions. The `ghcr.io/aweber-imbi/postgres` image has all three.
- `shared_preload_libraries` includes `age` and `pg_cron`.
- `cron.database_name` is the name of the target database. `pg_cron` can
  be created only in that database.
- The target database exists and is empty. No Imbi service connects to it
  before the restore. imbi-api creates the graph schema when it starts. A
  restore over that schema adds a second copy of each edge.
- You have the `IMBI_AUTH_ENCRYPTION_KEY` and `IMBI_CONFIG_ENCRYPTION_KEY`
  of the source system. Without them, Imbi cannot decrypt the stored
  credentials.

---

## 1. Take the Dump

Dump the whole database. Do not select schemas. The database holds the
graph (`imbi` and `ag_catalog`), the embeddings table, and the relational
schemas of the scheduler, agent tasks, workflows, secrets, and runner pools.

```bash
pg_dump --dbname "$POSTGRES_URL" --format custom --no-owner \
  --no-privileges --file imbi.dump
```

## 2. Prepare the Target Database

AGE and `pg_cron` must be installed before restore. `pg_cron` needs a
superuser, so the `imbi` role cannot create it during the restore. Connect
to the target DB as a superuser and run:

```sql
CREATE EXTENSION age;
CREATE EXTENSION pg_cron;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

## 3. Restore the Dump

```bash
pg_restore -d imbi --no-owner --role=imbi imbi.dump
```

The restore can log errors for objects in the `ag_catalog` schema that
`CREATE EXTENSION age` already made. You can ignore only these errors.
`pg_restore` continues after an error and prints the number of errors
(`errors ignored on restore: N`) at the end. Examine each error. If an
error is for an object outside `ag_catalog`, stop. Correct the cause, drop
and create the target database again, and restart from step 2.

## 4. Verify Graph Catalog Integrity

After restore, confirm all graph labels are registered:

```sql
-- Get the graph OID
SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'imbi';

-- List registered labels (note the graphid from above)
SELECT name, kind FROM ag_catalog.ag_label WHERE graph = <graphid> ORDER BY name;
```

## 5. Correct the Graph OID

AGE requires that `graphid` is the OID of the `imbi` schema. The dump
holds the OID of the source database. When they are different, graph
queries fail with "graph with oid N does not exist". Compare the two:

```sql
SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'imbi';
SELECT oid FROM pg_namespace WHERE nspname = 'imbi';
```

If they are different, run this in one transaction. Replace `<old>` with
the `graphid` and `<new>` with the schema OID:

```sql
BEGIN;
UPDATE ag_catalog.ag_graph SET name = '_imbi_stale', namespace = 'public'
  WHERE graphid = <old>;
INSERT INTO ag_catalog.ag_graph (graphid, name, namespace)
  VALUES (<new>, 'imbi', 'imbi');
UPDATE ag_catalog.ag_label SET graph = <new> WHERE graph = <old>;
DELETE FROM ag_catalog.ag_graph WHERE graphid = <old>;
COMMIT;
```

Use `<new>` as the `<graphid>` in the next steps.

## 6. Find Unregistered Labels

Physical label tables may exist without `ag_catalog.ag_label` entries. This causes
`DuplicateTable` errors when the application first accesses those labels.

```sql
SELECT tablename
FROM pg_tables
WHERE schemaname = 'imbi'
  AND tablename NOT IN (
    SELECT name FROM ag_catalog.ag_label WHERE graph = <graphid>
  )
ORDER BY tablename;
```

If this query returns rows, proceed to step 7. If empty, go to step 8.

## 7. Register Missing Labels

For each missing label, determine its kind: vertex (`v`) or edge (`e`). In Imbi,
edge labels are conventionally `ALL_CAPS` and vertex labels are `PascalCase`.

Run this once, substituting the correct list and your `graphid`:

```sql
INSERT INTO ag_catalog.ag_label (name, graph, id, kind, relation, seq_name)
SELECT
    name,
    <graphid>,
    (SELECT max(id) FROM ag_catalog.ag_label WHERE graph = <graphid>)
        + row_number() OVER (ORDER BY name),
    CASE WHEN name ~ '^[A-Z][a-z]' THEN 'v' ELSE 'e' END,
    'imbi."' || name || '"',
    name || '_id_seq'
FROM unnest(ARRAY[
    -- paste the tablename list from step 6 here
]) AS name;
```

## 8. Verify

```sql
-- All physical tables should now have catalog entries
SELECT tablename
FROM pg_tables
WHERE schemaname = 'imbi'
  AND tablename NOT IN (
    SELECT name FROM ag_catalog.ag_label WHERE graph = <graphid>
  );
-- Expected: 0 rows
```

## 9. Apply the Current Schema

Start imbi-api with the same keys as the source system. It applies the
graph schema and the relational schemas of the running release. Then run
these commands, so that the permissions, service accounts, and ClickHouse
schema match the running release:

```bash
imbi-api setup-permissions
imbi-api setup-service-accounts
imbi-api setup-clickhouse
```

Confirm that the logs show no `DuplicateTable` errors.

---

## Troubleshooting

**`DuplicateTable: relation "X" already exists`**
The label table exists but is not in `ag_catalog.ag_label`. Run steps 6 and 7.

**`graph with oid N does not exist`**
The graph OID is not the OID of the `imbi` schema. Run step 5.

**`ag_catalog` functions not found**
The `age` extension is not loaded for the session. Run:

```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

**Wrong `kind` assigned to a label**
Update the catalog entry directly:

```sql
UPDATE ag_catalog.ag_label SET kind = 'e' WHERE name = 'LABEL_NAME' AND graph = <graphid>;
```
