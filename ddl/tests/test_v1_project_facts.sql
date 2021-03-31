BEGIN;
  SELECT PLAN(25);

  SELECT lives_ok(
    $$INSERT INTO v1.namespaces (id, name, created_by, slug, icon_class) VALUES (1, 'test_namespace', 'test_user', 'test_slug', 'test_icon_class')$$,
    'create namespace');
  SELECT lives_ok(
    $$INSERT INTO v1.project_types (id, name, plural_name, created_by, slug) VALUES (1, 'test_project_type', 'tests', 'test_user', 'test_slug')$$,
    'create project type');

  SELECT lives_ok(
    $$INSERT INTO v1.projects (id, namespace_id, project_type_id, created_by, name, slug) VALUES (1, 1, 1, 'test_user', 'test_project', 'test_slug')$$,
    'create project');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (1, '{1}', 'enum_fact', 'enum', 'test_user', 25)$$,
    'create enum fact_type');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_enums (fact_type_id, value, created_by, score) VALUES (1, 'test_value 1', 'test_user', 20)$$,
     'create enum fact_type value 1');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_enums (fact_type_id, value, created_by, score) VALUES (1, 'test_value 2', 'test_user', 30)$$,
     'create enum fact_type value 2');

  SELECT lives_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, recorded_at, recorded_by, value) VALUES (1, 1, CURRENT_TIMESTAMP - interval '1 day', 'test_user', 'test_value 1')$$,
    'create an enum based fact, validating enum value');

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
         SET recorded_at = CURRENT_TIMESTAMP,
             recorded_by = 'test_user',
             value = 'test_value 2'
       WHERE project_id = 1
         AND fact_type_id = 1$$,
    'update an enum fact');

  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 1
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('test_value 2', 25, 30)$$,
    'the expected record is in the fact history table');

  SELECT throws_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, recorded_at, recorded_by, value) VALUES (1, 1, CURRENT_TIMESTAMP - interval '1 day', 'test_user', 'ad-hoc value')$$,
    'P0001', 'Value "ad-hoc value" for enum_fact (1) not found in v1.project_fact_type_enums',
    'throws when creating fact with invalid enum value');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (2, '{1}', 'freeform_fact', 'free-form', 'test_user', 0)$$,
    'create free-form fact_type');

  SELECT lives_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, recorded_at, recorded_by, value) VALUES (1, 2, CURRENT_TIMESTAMP - interval '1 day', 'test_user', 'free-form value here')$$,
    'create a free-form based fact');

  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 2
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('free-form value here', 0, 0)$$,
    'the expected record is in the fact history table');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_types (id, project_type_ids, name, fact_type, created_by, weight) VALUES (3, '{1}', 'range_fact', 'range', 'test_user', 25)$$,
    'create range fact_type');

  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_ranges (fact_type_id, min_value, max_value, created_by, score) VALUES (3, 0, 50, 'test_user', 0)$$,
     'create fact_type range 0-50');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_ranges (fact_type_id, min_value, max_value, created_by, score) VALUES (3, 51, 74, 'test_user', 50)$$,
     'create fact_type range 51-74');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_ranges (fact_type_id, min_value, max_value, created_by, score) VALUES (3, 75, 90, 'test_user', 80)$$,
     'create fact_type range 75-89');
  SELECT lives_ok(
    $$INSERT INTO v1.project_fact_type_ranges (fact_type_id, min_value, max_value, created_by, score) VALUES (3, 90, 100, 'test_user', 100)$$,
     'create fact_type range 90-100');

  SELECT lives_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, recorded_at, recorded_by, value) VALUES (1, 3, CURRENT_TIMESTAMP - interval '1 day', 'test_user', '33.3')$$,
    'create a range based fact');

  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 3
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('33.3', 25, 0)$$,
    'the expected record is in the fact history table');

  SELECT throws_ok(
    $$INSERT INTO v1.project_facts (project_id, fact_type_id, recorded_at, recorded_by, value) VALUES (1, 3, CURRENT_TIMESTAMP - interval '1 day', 'test_user', '256')$$,
    'P0001', '"256" for range_fact (3) not found in v1.project_fact_type_ranges',
    'throws when creating fact with invalid range value');

  SELECT lives_ok(
    $$UPDATE v1.project_facts
         SET recorded_at = CURRENT_TIMESTAMP,
             recorded_by = 'test_user',
             value = '92.6'
       WHERE project_id = 1
         AND fact_type_id = 3$$,
    'update a range fact');

  SELECT results_eq(
    $$SELECT value, weight, score
        FROM v1.project_fact_history
       WHERE project_id = 1
         AND fact_type_id = 3
    ORDER BY recorded_at DESC
       LIMIT 1$$,
    $$VALUES ('92.6', 25, 100)$$,
    'the expected record is in the fact history table');

  SELECT results_eq(
     $$SELECT score
         FROM v1.project_score_history
        WHERE project_id = 1
     ORDER BY changed_at DESC
        LIMIT 1$$,
     $$SELECT v1.project_score(1) AS score$$,
     'most recent score from history matches current score');

ROLLBACK;
