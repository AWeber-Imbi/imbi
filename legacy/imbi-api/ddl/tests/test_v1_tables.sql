BEGIN;
SELECT plan(17);

SELECT has_table('v1'::NAME, 'authentication_tokens'::NAME);
SELECT has_table('v1'::NAME, 'cookie_cutters'::NAME);
SELECT has_table('v1'::NAME, 'environments'::NAME);
SELECT has_table('v1'::NAME, 'group_members'::NAME);
SELECT has_table('v1'::NAME, 'groups'::NAME);
SELECT has_table('v1'::NAME, 'namespaces'::NAME);
SELECT has_table('v1'::NAME, 'project_dependencies'::NAME);
SELECT has_table('v1'::NAME, 'project_fact_history'::NAME);
SELECT has_table('v1'::NAME, 'project_fact_type_options'::NAME);
SELECT has_table('v1'::NAME, 'project_fact_types'::NAME);
SELECT has_table('v1'::NAME, 'project_facts'::NAME);
SELECT has_table('v1'::NAME, 'project_link_types'::NAME);
SELECT has_table('v1'::NAME, 'project_links'::NAME);
SELECT has_table('v1'::NAME, 'project_types'::NAME);
SELECT has_table('v1'::NAME, 'project_urls'::NAME);
SELECT has_table('v1'::NAME, 'projects'::NAME);
SELECT has_table('v1'::NAME, 'users'::NAME);

SELECT * FROM finish();
ROLLBACK;
