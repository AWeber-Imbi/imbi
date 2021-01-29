SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS project_links (
  project_id        INTEGER                   NOT NULL,
  link_type_id      INTEGER                   NOT NULL,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  url               TEXT                      NOT NULL,
  PRIMARY KEY (project_id, link_type_id),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (link_type_id) REFERENCES project_link_types (id) ON DELETE RESTRICT ON UPDATE CASCADE
);

COMMENT ON TABLE project_links IS 'Project specific links';
COMMENT ON COLUMN project_links.project_id IS 'The project ID';
COMMENT ON COLUMN project_links.link_type_id IS 'The link type ID';
COMMENT ON COLUMN project_links.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_links.created_by IS 'The user created the record';
COMMENT ON COLUMN project_links.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_links.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_links.url IS 'The URL of the link';

GRANT SELECT ON project_links TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_links TO writer;
