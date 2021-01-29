BEGIN;
  SELECT PLAN(10);

  SELECT lives_ok(
    $$INSERT INTO v1.namespaces (id, name, created_by, slug, icon_class) VALUES (1, 'test_namespace', 'test_user', 'test_slug', 'test_icon_class')$$,
    'create namespace');
  SELECT lives_ok(
    $$INSERT INTO v1.project_types (id, name, created_by, slug) VALUES (1, 'test_project_type', 'test_user', 'test_slug')$$,
    'create project type');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_id, fact_type, created_by, weight) VALUES (1, 1, 'test_fact', 'test_user', 25)$$,
    'create project fact_type');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_options (fact_type_id, value, created_by, score) VALUES (1, 'test_value 1', 'test_user', 20)$$,
     'create project fact type option 1');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_options (fact_type_id, value, created_by, score) VALUES (1, 'test_value 2', 'test_user', 30)$$,
     'create project fact type option 2');
  SELECT lives_ok(
    $$INSERT INTO v1.projects (id, namespace_id, project_type_id, created_by, name, slug) VALUES (1, 1, 1, 'test_user', 'test_project', 'test_slug')$$,
    'create project');
  SELECT lives_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, created_at, created_by, value) VALUES (1, 1, CURRENT_TIMESTAMP - interval '1 day', 'test_user', 'test_value 1')$$,
    'create a fact');
  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 1
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('test_value 1', 25, 20)$$,
    'the expected record is in the fact history table');
  SELECT lives_ok(
    $$UPDATE v1.project_facts
         SET last_modified_at = CURRENT_TIMESTAMP,
             last_modified_by = 'test_user',
             value = 'test_value 2'
       WHERE project_id = 1
         AND fact_type_id = 1$$,
    'update a fact');
  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 1
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('test_value 2', 25, 30)$$,
    'the expected record is in the fact history table');
ROLLBACK;
