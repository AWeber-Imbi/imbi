# How to Restore an Imbi Database Backup

Restore a `pg_dump` backup of the Imbi database, including the Apache AGE graph.

**Prerequisites**: AGE extension installed on the target PostgreSQL instance, target DB created and empty.

---

## 1. Prepare the Target Database

AGE must be installed before restore. Connect to the target DB and run:

```sql
CREATE EXTENSION age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

## 2. Restore the Dump

```bash
pg_restore -d imbi -Fc --no-owner --role=imbi imbi.dump
```

Or for plain SQL:

```bash
psql -d imbi -f imbi.sql
```

## 3. Verify Graph Catalog Integrity

After restore, confirm all graph labels are registered:

```sql
-- Get the graph OID
SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'imbi';

-- List registered labels (note the graphid from above)
SELECT name, kind FROM ag_catalog.ag_label WHERE graph = <graphid> ORDER BY name;
```

## 4. Find Unregistered Labels

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

If this query returns rows, proceed to step 5. If empty, the restore is complete.

## 5. Register Missing Labels

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
    -- paste the tablename list from step 4 here
]) AS name;
```

## 6. Verify

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

Restart the application and confirm no `DuplicateTable` errors occur.

---

## Troubleshooting

**`DuplicateTable: relation "X" already exists`**
The label table exists but is not in `ag_catalog.ag_label`. Run steps 4 and 5.

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
