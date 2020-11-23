BEGIN;
SELECT plan(4);

SELECT has_role('admin');
SELECT has_role('reader');
SELECT has_role('writer');
SELECT has_role('imbi');

SELECT * FROM finish();
ROLLBACK;
