SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS projects (
  id                     SERIAL                    NOT NULL  PRIMARY KEY,
  namespace_id           INT4                      NOT NULL,
  project_type_id        INT4                      NOT NULL,
  created_at             TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by             TEXT                      NOT NULL,
  last_modified_at       TIMESTAMP WITH TIME ZONE,
  last_modified_by       TEXT,
  "name"                 TEXT                      NOT NULL,
  slug                   TEXT                      NOT NULL,
  description            TEXT,
  environments           TEXT[],
  archived               BOOLEAN                   NOT NULL  DEFAULT FALSE,
  gitlab_project_id      INT4,
  sentry_project_slug    TEXT,
  sonarqube_project_key  TEXT,
  pagerduty_service_id   TEXT,
  UNIQUE (namespace_id, project_type_id, name),
  FOREIGN KEY (namespace_id) REFERENCES namespaces (id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (project_type_id) REFERENCES project_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE UNIQUE INDEX projects_namespace_id_project_type_id_slug_key ON v1.projects (namespace_id, project_type_id, slug) WHERE archived IS FALSE;

COMMENT ON TABLE projects IS 'Projects';
COMMENT ON COLUMN projects.id IS 'Surrogate key for URLs and linking';
COMMENT ON COLUMN projects.namespace_id IS 'The ID for the namespace the project belongs to';
COMMENT ON COLUMN projects.project_type_id IS 'The ID for the type of project (API, Consumer, Database, etc)';
COMMENT ON COLUMN projects.created_at IS 'When the record was created at';
COMMENT ON COLUMN projects.created_by IS 'The user created the record';
COMMENT ON COLUMN projects.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN projects.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN projects.name IS 'The name of the project';
COMMENT ON COLUMN projects.slug IS 'The project slug used in paths';
COMMENT ON COLUMN projects.description IS 'Description of the high-level purpose and context for the project';
COMMENT ON COLUMN projects.environments IS 'The operational environments the project is available in';
COMMENT ON COLUMN projects.archived IS 'Indicates that the project is archived and should not appear in normal search results';
COMMENT ON COLUMN projects.gitlab_project_id IS 'If set, specifies the GitLab project ID for the GitLab integration';
COMMENT ON COLUMN projects.sentry_project_slug IS 'If set, specifies the project slug for the Sentry integration';
COMMENT ON COLUMN projects.sonarqube_project_key IS 'If set, specifies the project slug for the SonarQube integration';
COMMENT ON COLUMN projects.pagerduty_service_id IS 'If set, specifies the service id for the PagerDuty integration';

GRANT SELECT ON projects TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON projects TO writer;
