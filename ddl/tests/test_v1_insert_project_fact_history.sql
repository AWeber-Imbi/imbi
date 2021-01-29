BEGIN;
SELECT PLAN(2);
--fixtures
INSERT INTO v1.namespaces (name, created_by, slug, icon_class) VALUES ('test_namespace', 'test_user', 'test_slug', 'test_icon_class');
INSERT INTO v1.project_types (name, created_by, slug) VALUES ('test_project_type', 'test_user', 'test_slug');
INSERT INTO v1.projects (namespace, name, created_by, slug, project_type) VALUES ('test_namespace', 'test_project', 'test_user', 'test_slug', 'test_project_type');
INSERT INTO v1.projects (namespace, name, created_by, slug, project_type) VALUES ('test_namespace', 'test_project_2', 'test_user', 'test_slug_2', 'test_project_type');
INSERT INTO v1.project_fact_types (project_type, fact_type, created_by) VALUES ('test_project_type', 'test_fact_type', 'test_user');
INSERT INTO v1.project_fact_type_options (project_type, fact_type, value, created_by) VALUES ('test_project_type', 'test_fact_type', 'test_value', 'test_user');
INSERT INTO v1.project_facts (namespace, name, fact_type, created_by, value) VALUES ('test_namespace', 'test_project', 'test_fact_type', 'test_user', 'test_value');

SELECT results_eq(
  $$SELECT "name" FROM v1.project_fact_history WHERE "name"='test_project'$$,
  $$VALUES ('test_project')$$,
  'Record exists in v1.project_fact_history');

UPDATE v1.project_facts
   SET "name" = 'test_project_2'
 WHERE "name" = 'test_project';

 SELECT results_eq(
  $$SELECT "name" FROM v1.project_fact_history WHERE "name"='test_project_2'$$,
  $$VALUES ('test_project_2')$$,
  'Record exists in v1.project_fact_history');

ROLLBACK;
