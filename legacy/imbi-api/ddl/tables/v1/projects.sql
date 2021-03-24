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
  UNIQUE (namespace_id, project_type_id, name),
  UNIQUE (namespace_id, project_type_id, slug),
  FOREIGN KEY (namespace_id) REFERENCES namespaces (id) ON UPDATE CASCADE ON DELETE RESTRICT,
  FOREIGN KEY (project_type_id) REFERENCES project_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

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

GRANT SELECT ON projects TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON projects TO writer;
