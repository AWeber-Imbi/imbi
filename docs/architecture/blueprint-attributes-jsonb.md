# Blueprint Attributes in JSONB

Status: Draft for review (implementation plan WP0.5), 2026-09-30.

Blueprints add fields to a project, an environment, a team, and the
other blueprint tables. In the graph, each field is an extra property on
the vertex or the edge. In the relational schema, the fields go into one
column, `attributes`, of the domain `jsonb_object` (D9). This page gives
the rules for the values in that column, and the rule for indexes.

The tables with `attributes` are `projects`, `project_environments`,
`environments`, `teams`, `project_types`, `organizations`, and
`integrations`.

## Current behavior

These facts come from the code on `feature/age-relational` (5acc05a) and
from a test on the scratch PostgreSQL 18.3 server with AGE.

| Where | What it does today |
|---|---|
| `libraries/common/src/imbi/common/blueprints.py`, `apply_blueprints()` | Makes a Pydantic model from the enabled blueprints. A property with a schema `default` gets that default. A property that is not `required` and has no default becomes optional, with the default `None`. Type mapping: `string` to `str` (or `Literal` for a string enum, with a case-insensitive validator; `EmailStr`, `HttpUrl`, `datetime`, `date`, or `time` for a `format`), `integer` to `int`, `number` to `float`, `boolean` to `bool`, `array` to `list[T]`, `object` to `dict`. |
| `endpoints/projects.py`, create and update | Validates the body with that model, then writes `model_dump(mode='json')`. Unknown keys are dropped on create (`extra='ignore'`). On update, the code passes the existing keys back in, but `SET` changes only the keys of the model, so a key that no blueprint names stays on the vertex. |
| AGE, `CREATE (p {k: null})` | Does not store the key (tested). |
| AGE, `SET p.k = null` | Removes the key (tested). So the graph has no stored null: a missing key and null are the same. |
| AGE, `p.flag = true` for the string `'true'` | False (tested). `3 = 3.0` is true. `1 = true` is false. |
| `endpoints/projects.py:2063`, `_coerce_filter_value()` | Converts a list filter value to the attribute's declared type: `'true'`/`'false'` to a boolean, a number to `int` or `float`. It rejects a value that the type cannot hold with 400. Other types stay strings. |
| `endpoints/projects.py:2121`, `_build_attribute_filter()` | Operators `eq`, `ne`, `in`, `not_in`, `exists`, `not_exists`. `ne` and `not_in` use `<>`, so a project without the key does not match. `exists` is `IS NOT NULL`. The list is always `ORDER BY p.name`. No operator compares with `<` or `>`, and no list sorts by an attribute. |
| `apps/api/src/imbi/api/blueprint_attributes.py`, `resolve()` | Every property of every enabled `Project` node blueprint is filterable. |
| `libraries/common/src/imbi/common/scoring/engine.py` | Scores one project at a time. It reads the project by id through the blueprint model, then evaluates each policy in Python. `apps/api/src/imbi/api/scoring/queue.py` selects the projects to score by project type, not by an attribute value. |

The null-scoring rule of `libraries/common/src/imbi/common/scoring/`,
quoted from the code:

- `attribute.compute_base_score()`: "No applicable policies → score is
  100. Missing or unmapped values contribute a mapped score of 0 to the
  weighted average." The code is `score = 0.0 if mapped is None else
  mapped`.
- `AttributePolicy.evaluate()`: "Map a project value to 0-100; `None` if
  missing/unmapped." A `None` value returns `None`. A value that is not a
  key of `value_score_map`, or a value outside every range of
  `range_score_map`, returns `None`. A value that `float()` cannot
  convert returns `None`.
- `PresencePolicy` and `LinkPresencePolicy` use `is_missing()`: `None`,
  a string that is empty after `strip()`, and an empty list, tuple, set,
  or dict are missing. `0` and `false` are present.
- `AgePolicy.evaluate()`: `None`, or a value that is not a date or an
  ISO 8601 string, returns `None`.
- `AnalysisResultPolicy.evaluate()`: no result, or a status that is not
  `pass`, `warn`, or `fail`, returns `None`.
- `DeploymentStatusPolicy.evaluate()`: no deployment uses the
  `'missing'` key (default 100). A status that the map does not have
  also uses `'missing'`.
- `ConditionPolicy`: "it never returns `None`". `present` and `absent`
  use `is_missing()`. A numeric operator (`gt`, `ge`, `lt`, `le`) is
  false when either side is not a number. `eq` and `ne` compare
  `_value_key()` of both sides.
- `_value_key()`: a boolean becomes `'true'` or `'false'`. Every other
  value becomes `str(value)`. The docstring says: "AGE persists some
  boolean attributes as real booleans and others as the strings
  `'true'`/`'false'`". So the scoring map matches both forms, but the
  list filter matches only the stored boolean.

## Rules

Each rule has an example. `a` is the `attributes` column.

### 1. Missing key and JSON null

**Rule:** the application never stores a JSON null in `attributes`. To
clear a field, it removes the key. The ETL removes a key whose value is
null (the graph has none; see the table above). Readers treat a missing
key as "not set".

This keeps the graph behavior: missing and null are the same. It also
makes `?` and `->>` agree. In JSONB, `'{"k": null}'::jsonb ? 'k'` is
true, but `'{}'::jsonb ? 'k'` is false.

Example: a PATCH with `{"framework": null}` runs
`a = a - 'framework'`, not `jsonb_set(a, '{framework}', 'null')`.

### 2. Boolean against string

**Rule:** a field whose blueprint type is `boolean` holds a JSON
boolean. The application converts on write (the Pydantic model does
this today). The ETL converts the strings `'true'` and `'false'` to
JSON booleans for a field whose blueprint type is `boolean`, and logs
each conversion. A field whose type is `string` keeps the string.

A comparison binds a JSON value of the declared type. In JSONB,
`'{"a": true}'::jsonb @> '{"a": "true"}'` is false.

Example: `filter=deprecated:eq:true` becomes
`a -> 'deprecated' = 'true'::jsonb`, with the value bound as
`psycopg.types.json.Jsonb(True)`.

Proposed for Gavin: the ETL conversion is new. Today the list filter
does not match a stored string `'true'`. After the conversion, it does.
Before the conversion runs, the audit (WP1.9) counts, for each
blueprint field of type `boolean`, the values that are JSON booleans,
the exact strings `'true'` and `'false'`, and all other values (case or
space variants, other strings). The ETL converts only the two exact
strings, keeps each original value in its report, and does not convert
any other value. The graph has no blueprint version for each row
(README Differences 10), so the ETL cannot know the type of a field at
the time of the write. The audit counts show whether this is a problem.

After the migration, the type is strict. The code does not accept both
forms.

### 3. Numbers and sort order

**Rule:** a field whose type is `integer` or `number` holds a JSON
number. Equality compares JSONB values: `'3'::jsonb = '3.0'::jsonb` is
true, as `3 = 3.0` is in AGE today. Do not compare `->>` text for a
number: `'{"n": 3.0}'::jsonb ->> 'n'` is `'3.0'`, not `'3'`. A range or
a sort casts the value, for example `(a ->> 'n')::bigint` for `integer`
and `(a ->> 'n')::double precision` for `number`.

Example: `range_score_map` stays in Python (`float(value)`). A future
list sort on `replicas` uses `ORDER BY (a ->> 'replicas')::bigint NULLS
LAST, name`.

Do not sort on the JSONB value itself. JSONB orders by type first
(object, array, boolean, number, string, null), so a mixed column sorts
in a way that no person expects.

### 4. Arrays and membership

**Rule:** a field whose type is `array` holds a JSON array. Membership
of a string uses `?` on the field: `a -> 'languages' ? 'python'`. A
number or boolean element uses containment:
`a -> 'ports' @> '[8080]'`. `?` tests only string elements (and object
keys), so guard each membership test with
`jsonb_typeof(a -> 'k') = 'array'`.

Today the list filter has no membership operator. `eq` on an array
field compares the whole value with a string, so it never matches. A
new membership operator is new API behavior, and needs a decision.

### 5. Defaults

**Rule:** the database stores no blueprint default. The column default
is `'{}'`. The application applies the blueprint default when it builds
the model, as it does today.

Today the create and update routes write the default into the vertex,
because they validate through the blueprint model and write
`model_dump()`. A project that existed before a default was added, and
that no one has updated since, has no key. For that project:

- Scoring sees the default: `engine.py` reads the project through the
  blueprint model, which fills it in.
- `GET /projects/{id}` and the list do not show the key: they read the
  stored properties into `ProjectResponse` (`extra='allow'`), not
  through the blueprint model.
- The list filter `exists` does not match it: it reads the stored
  value.
- The next PATCH stores the default.

The relational code keeps this behavior. The replay comparison
(execution plan section 6) checks it.

Example: a blueprint adds `tier` with `default: "3"`. An old project
has no `tier` key. Scoring uses `"3"`. `GET /projects/{id}` has no
`tier`, and `filter=tier:exists` does not return the project. The
blueprint compliance check reports `use-default` for it.

### 6. Unknown properties

**Rule:** the application writes only the keys that the applicable
blueprints name. An unknown key in a request body is ignored, as today.
A key that no applicable blueprint names any more stays in the row until
a person removes it. The blueprint compliance check
(`apps/api/src/imbi/api/blueprint_compliance.py`,
`_stale_blueprint_properties()`) reports it, as today.

An update writes the merged object with `a || $1::jsonb` for the set
keys and `a - $2::text[]` for the cleared keys. It does not replace the
whole object, so a stale key is not lost by accident. The application
removes JSON nulls and unknown keys from `$1` before the statement, and
a key cannot be in both `$1` and `$2`. `||` merges only the top level:
a field of type `object` is replaced as a whole, as `SET` does today.

JSONB does not keep the key order of the input. The API response gets
its field order from the blueprint, not from the column.

Example: blueprint `python` no longer applies to a project whose type
changed. `a` still has `python_version`. The compliance report lists it
as stale.

### 7. Null in scoring

**Rule:** the scoring engine keeps the rule that it has today. A missing
key reaches a policy as its blueprint default, or as `None` when there
is no default, the same as today, because rule 1 stores no null and the
model fills a missing field.
The relational repository returns `a` through the same blueprint model,
so `compute_base_score()` does not change.

Example: an `AttributePolicy` on `programming_language` with weight 10,
for a project with no `programming_language` key, gives
`mapped_score = 0` and adds 0 to the weighted sum. The total weight
still includes 10.

### 8. Filter predicates and missing keys

**Rule:** the list filter keeps today's result for each case. In SQL, a
comparison with a missing key gives NULL, and `WHERE` drops the row.
This gives the same result as AGE today. Each operator, with `$1` a
JSONB value of the declared type:

| Operator | SQL | Key missing | Key has another type |
|---|---|---|---|
| `eq` | `a -> 'k' = $1` | no match | no match |
| `ne` | `a -> 'k' <> $1` | no match | match |
| `in` | `(a -> 'k' = $1 OR a -> 'k' = $2 ...)` | no match | no match |
| `not_in` | `(a -> 'k' <> $1 AND a -> 'k' <> $2 ...)` | no match | match |
| `exists` | `a ? 'k'` | no match | match |
| `not_exists` | `NOT (a ? 'k')` | match | no match |

`exists` can use `a ? 'k'`, because rule 1 stores no null. An empty
value list for `in` or `not_in` is a 400 today, and stays a 400. Do not
write `NOT (a -> 'k' = $1)` for `ne`: the result is the same for a
missing key (NULL), but the form hides the rule.

The WP that owns the list (WP2.2) adds a test for each row of this
table, and the replay comparison checks the AGE-era results.

## Indexes

No GIN index on `attributes` (D9). Under row-level security, PostgreSQL
uses an index condition only when its operator is leakproof. The JSONB
operators are not leakproof, so for `imbi_app` they are filters on the
rows of one organization.

Checked in `pg_proc.proleakproof` on PostgreSQL 18.3:

| Leakproof (can be an index condition) | Not leakproof (always a filter) |
|---|---|
| `texteq`, `text_lt`, `int8eq`, `int8lt`, `float8eq`, `float8lt`, `booleq`, `timestamptz_eq`, `timestamptz_lt` | `jsonb_eq`, `jsonb_contains` (`@>`), `jsonb_exists` (`?`), `jsonb_object_field_text` (`->>`), `numeric_eq`, `numeric_lt` |

**Rule:** add a generated column with a btree index
`(organization_id, <column>)` only for an attribute that a list filters
or sorts on often, and only when a measurement shows the filter is
slow. For an index condition under RLS, the column type must be
`text`, `bigint`, `double precision`, `boolean`, or `timestamptz`. The
`numeric` operators are not leakproof, so for `imbi_app` a `numeric`
column is always a filter. Use `numeric` only where exact decimals are
a product rule, and accept the filter. `double precision` loses
precision above 2^53 and for some decimals.

Two limits on a generated column:

- The expression must be immutable. A cast from text to `timestamptz`
  is not immutable (it depends on `TimeZone` and `DateStyle`), so a
  date-time attribute needs a different form, for example an
  immutable wrapper function that parses only one ISO 8601 form with an
  explicit offset.
- A cast that fails stops the INSERT or UPDATE. `jsonb_typeof()` is not
  enough: `1.5` is a JSON number and does not cast to `bigint`, and a
  large number overflows. Use an immutable conversion function that
  returns NULL for a value that does not fit, or a CHECK that rejects
  the value before the column exists. Validate the value in the
  application before the write too.

Measure with `EXPLAIN (ANALYZE, BUFFERS)` as `imbi_app`, in an
organization context, never as the owner or a superuser: row-level
security does not apply to them in the same way.

### Attributes that scoring and the list filters read

| Reader | Attributes | SQL condition on the attribute | Generated column |
|---|---|---|---|
| Scoring policies (`scoring/`) | `attribute_name` of each attribute, presence, and age policy; the keys of `links`; the attributes of a condition tree | None. The engine reads one project by id and evaluates in Python. The queue selects projects by project type. | Not necessary |
| Project list `filter` (`endpoints/projects.py`) | Any property of an enabled `Project` node blueprint (`blueprint_attributes.resolve()`) | Equality, inequality, and NULL tests, inside one organization. The order is always `name`. | Not necessary today |
| Project list, archived | `archived_at` (a real column, not an attribute) | `archived_at IS NULL` | Not an attribute |

Reason for "not necessary today": production has one organization and
701 projects (evaluation, 2026-08-20). The organization index gives the
rows of one organization, and a JSONB filter on 701 rows is small. The
UI does not use `filter`. The assistant and the Slack bot use it
(their `system_prompt.md` tells the model to).

Which attribute names the filters use in production is data, not code.
This page does not list them: the blueprints are rows, and this work
package did not read production. The rehearsal (WP3.2) gives the p50 and
p95 of the project list with a filter. If a filtered list is slower than
its AGE-era side by more than 20 percent, the WP that owns the list
(WP2.2) adds a generated column for the attributes that the slow
requests use.

## Rhona review

Rhona reviewed this page on 2026-09-30 (session
age-g-docs-2026-09-30).

Adopted:

- Safe casts: `jsonb_typeof()` does not prove that a value fits the
  target type (the generated column limits).
- An exact predicate for each filter operator and each case of a
  missing or wrongly typed key, with a test for each (rule 8).
- The boolean conversion: count first, convert only the exact strings,
  keep the originals in the report, strict type after the migration
  (rule 2).
- The array type guard for `?` (rule 4), the top-level merge and key
  order (rule 6), and measurement as `imbi_app` (Indexes).
- `numeric` is a product choice, not a forbidden type.

Not adopted:

- A blueprint version for each row. The schema has no version column
  (README Differences 10) because no code writes one. The audit counts
  of rule 2 show whether a field changed type.
- A review of `current_organization_id()` and the RLS context. README
  "Row-level security" defines them (a STABLE SQL function,
  transaction-local settings, USING and WITH CHECK), and WP1.1 tests
  them. They are not part of the attribute rules.
- A CHECK that rejects JSON null in `attributes`. A recursive check is
  expensive on each write, and the repository and the ETL are the only
  writers. The
  reconciliation report can count null values after the ETL instead.

## Open points for review

1. Rule 2: the ETL converts the strings `'true'` and `'false'` for a
   `boolean` field. Accept, or keep the strings?
2. Rule 4: a membership operator for array fields in the list filter is
   new API behavior. Add it with the relational list, or later?
3. Rule 5: the database does not store defaults. Scoring then sees a
   default that the API response and the list filter do not show. This
   is today's behavior. Keep it, or make the ETL write the defaults?
