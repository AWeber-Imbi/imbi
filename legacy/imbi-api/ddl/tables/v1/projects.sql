SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS projects (
  namespace             TEXT                      NOT NULL,
  "name"                TEXT                      NOT NULL,
  created_at            TIMESTAMP WITH TIME ZONE  NOT NULL              DEFAULT CURRENT_TIMESTAMP,
  created_by            TEXT                      NOT NULL,
  last_modified_at      TIMESTAMP WITH TIME ZONE,
  last_modified_by      TEXT,
  slug                  TEXT                      NOT NULL,
  description           TEXT,
  project_type          TEXT                      NOT NULL,
  data_center           TEXT,
  environments          TEXT[],
  configuration_system  TEXT,
  deployment_type       TEXT,
  orchestration_system  TEXT,
  PRIMARY KEY (namespace, "name"),
  FOREIGN KEY (namespace) REFERENCES namespaces ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (data_center) REFERENCES data_centers ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (project_type) REFERENCES project_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (configuration_system) REFERENCES configuration_systems ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (deployment_type) REFERENCES deployment_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (orchestration_system) REFERENCES orchestration_systems ("name") ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE UNIQUE INDEX project_namespace_slug ON projects (namespace, slug);

COMMENT ON TABLE projects IS 'Projects';
COMMENT ON COLUMN projects.namespace IS 'The namespace the project belongs to';
COMMENT ON COLUMN projects.name IS 'The name of the project';
COMMENT ON COLUMN projects.created_at IS 'When the record was created at';
COMMENT ON COLUMN projects.created_by IS 'The user created the record';
COMMENT ON COLUMN projects.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN projects.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN projects.slug IS 'The project slug used in paths';
COMMENT ON COLUMN projects.description IS 'Description of the high-level purpose and context for the project';
COMMENT ON COLUMN projects.data_center IS 'The data center that the project is run in';
COMMENT ON COLUMN projects.environments IS 'The operational environments the project is available in';
COMMENT ON COLUMN projects.project_type IS 'The type of project (API, Consumer, Database, etc)';
COMMENT ON COLUMN projects.configuration_system IS 'The system used to configure the project (Ansible, Consul, etc)';
COMMENT ON COLUMN projects.deployment_type IS 'How the project is deployed (Jenkins, GitLab-CI, etc)';
COMMENT ON COLUMN projects.orchestration_system IS 'The system used to manage the runtime state of the project (Kubernetes, Nomad, etc)';

GRANT SELECT ON projects TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON projects TO writer;
