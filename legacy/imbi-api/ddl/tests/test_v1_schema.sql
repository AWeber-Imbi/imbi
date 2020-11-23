BEGIN;
SELECT plan(1);

SELECT has_schema('v1'::NAME);

SELECT * FROM finish();
ROLLBACK;
