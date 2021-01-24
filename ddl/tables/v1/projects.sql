SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS projects (
  id                   UUID NOT NULL PRIMARY KEY DEFAULT uuid_generate_v4(),
  created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modified_at          TIMESTAMP WITH TIME ZONE,
  "name"               TEXT NOT NULL,
  slug                 TEXT NOT NULL,
  description          TEXT,
  owned_by             TEXT NOT NULL,
  data_center          TEXT NOT NULL,
  project_type         TEXT NOT NULL,
  configuration_system TEXT,
  deployment_type      TEXT,
  orchestration_system TEXT,
  environments         TEXT[],
  FOREIGN KEY (owned_by) REFERENCES teams ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (data_center) REFERENCES data_centers ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (project_type) REFERENCES project_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (configuration_system) REFERENCES configuration_systems ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (deployment_type) REFERENCES deployment_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (orchestration_system) REFERENCES orchestration_systems ("name") ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE UNIQUE INDEX unique_team_project_name ON projects (owned_by, "name");
CREATE UNIQUE INDEX unique_team_project_slug ON projects (owned_by, slug);

COMMENT ON TABLE projects IS 'Services';

COMMENT ON COLUMN projects.id IS 'Unique ID for the project';
COMMENT ON COLUMN projects.created_at IS 'When the record was created at';
COMMENT ON COLUMN projects.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN projects.slug IS 'Service path slug / abbreviation';
COMMENT ON COLUMN projects.owned_by IS 'The name of the team that is responsible for the project';
COMMENT ON COLUMN projects.data_center IS 'The data center that the project is run in';
COMMENT ON COLUMN projects.project_type IS 'The type of project (API, Consumer, Database, etc)';
COMMENT ON COLUMN projects.configuration_system IS 'The system used to configure the project (Ansible, Consul, etc)';
COMMENT ON COLUMN projects.deployment_type IS 'How the project is deployed (Jenkins, GitLab-CI, etc)';
COMMENT ON COLUMN projects.orchestration_system IS 'The system used to manage the runtime state of the project (Kubernetes, Nomad, etc)';
COMMENT ON COLUMN projects.environments IS 'The operational environments the project is available in';

GRANT SELECT ON projects TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON projects TO writer;
