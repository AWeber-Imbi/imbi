BEGIN;
SELECT plan(16);

SELECT has_table('v1'::NAME, 'authentication_tokens'::NAME);
SELECT has_table('v1'::NAME, 'configuration_systems'::NAME);
SELECT has_table('v1'::NAME, 'cookie_cutters'::NAME);
SELECT has_table('v1'::NAME, 'data_centers'::NAME);
SELECT has_table('v1'::NAME, 'deployment_types'::NAME);
SELECT has_table('v1'::NAME, 'environments'::NAME);
SELECT has_table('v1'::NAME, 'group_members'::NAME);
SELECT has_table('v1'::NAME, 'groups'::NAME);
SELECT has_table('v1'::NAME, 'orchestration_systems'::NAME);
SELECT has_table('v1'::NAME, 'project_dependencies'::NAME);
SELECT has_table('v1'::NAME, 'project_link_types'::NAME);
SELECT has_table('v1'::NAME, 'project_links'::NAME);
SELECT has_table('v1'::NAME, 'project_types'::NAME);
SELECT has_table('v1'::NAME, 'projects'::NAME);
SELECT has_table('v1'::NAME, 'teams'::NAME);
SELECT has_table('v1'::NAME, 'users'::NAME);

SELECT * FROM finish();
ROLLBACK;
