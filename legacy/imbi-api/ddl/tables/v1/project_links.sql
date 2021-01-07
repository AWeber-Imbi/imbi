SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS project_links (
  project_id    UUID NOT NULL,
  link_type     TEXT NOT NULL,
  url           TEXT NOT NULL,
  created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modified_at   TIMESTAMP WITH TIME ZONE,
  PRIMARY KEY   (project_id, url),
  FOREIGN KEY   (project_id) REFERENCES projects (id) ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY   (link_type) REFERENCES project_link_types (link_type) ON DELETE RESTRICT ON UPDATE CASCADE
);

COMMENT ON TABLE project_links IS 'Project specific links';
COMMENT ON COLUMN project_links.project_id IS 'The project the link is for';
COMMENT ON COLUMN project_links.link_type IS 'The type of link';
COMMENT ON COLUMN project_links.url IS 'The URL of the link';
COMMENT ON COLUMN project_links.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_links.modified_at IS 'When the record was last modified at';

GRANT SELECT ON project_links TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_links TO writer;
