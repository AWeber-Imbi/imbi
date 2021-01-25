SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS project_links (
  namespace         TEXT                      NOT NULL,
  "name"            TEXT                      NOT NULL,
  link_type         TEXT                      NOT NULL,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  url               TEXT                      NOT NULL,
  PRIMARY KEY (namespace, "name", link_type),
  FOREIGN KEY (namespace, "name") REFERENCES projects (namespace, "name") ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (link_type) REFERENCES project_link_types (link_type) ON DELETE RESTRICT ON UPDATE CASCADE
);

COMMENT ON TABLE project_links IS 'Project specific links';
COMMENT ON COLUMN project_links.namespace IS 'The project namespace';
COMMENT ON COLUMN project_links.name IS 'The project name';
COMMENT ON COLUMN project_links.link_type IS 'The type of link';
COMMENT ON COLUMN project_links.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_links.created_by IS 'The user created the record';
COMMENT ON COLUMN project_links.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_links.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_links.url IS 'The URL of the link';

GRANT SELECT ON project_links TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_links TO writer;
