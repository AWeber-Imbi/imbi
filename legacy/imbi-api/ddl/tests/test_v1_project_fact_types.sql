BEGIN;
  SELECT PLAN(7);

  SELECT lives_ok(
    $$INSERT INTO v1.project_types (id, name, plural_name, created_by, slug) VALUES (1, 'test type 1', 'type 1 tests', 'test_user', 'test1')$$,
    'create project type test1');

  SELECT lives_ok(
    $$INSERT INTO v1.project_types (id, name, plural_name, created_by, slug) VALUES (2, 'test type 2', 'type 2 tests', 'test_user', 'test2')$$,
    'create project type test2');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (1, '{1, 2}', 'fact-type-1', 'free-form', 'test_user', 0)$$,
    'create fact type with valid project type ids');

  SELECT throws_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (2, '{1, 2, 3}', 'fact-type-2', 'free-form', 'test_user', 0)$$,
    'P0001', 'project_type_id 3 not found in v1.project_types',
    'create fact type with invalid project type ids');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (3, NULL, 'fact-type-3', 'free-form', 'test_user', 0)$$,
    'create fact type with NULL project type ids');

  SELECT lives_ok(
    $$DELETE FROM v1.project_types WHERE id = 2$$,
    'delete project type test2');

  SELECT results_eq(
    $$SELECT project_type_ids
        FROM v1.project_fact_types
       WHERE id = 1$$,
    $$VALUES (ARRAY[1])$$,
    'project type test2 not present in project fact type 1');



ROLLBACK;
