SET search_path=v1;

CREATE TABLE IF NOT EXISTS cookie_cutters (
  "name"             TEXT                      NOT NULL  PRIMARY KEY,
  created_at         TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by         TEXT                      NOT NULL,
  last_modified_at   TIMESTAMP WITH TIME ZONE,
  last_modified_by   TEXT,
  description        TEXT,
  "type"             cookie_cutter_type        NOT NULL  DEFAULT 'project',
  project_type_id    INTEGER                   NOT NULL,
  url                TEXT                      NOT NULL,
  FOREIGN KEY (project_type_id) REFERENCES v1.project_types (id) ON DELETE CASCADE ON UPDATE CASCADE
);

COMMENT ON TABLE cookie_cutters IS 'Cookie Cutters';
COMMENT ON COLUMN cookie_cutters.name IS 'Cookie Cutter name';
COMMENT ON COLUMN cookie_cutters.created_at IS 'When the record was created at';
COMMENT ON COLUMN cookie_cutters.created_by IS 'The user created the record';
COMMENT ON COLUMN cookie_cutters.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN cookie_cutters.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN cookie_cutters.description IS 'The description of the cookie cutter';
COMMENT ON COLUMN cookie_cutters.type IS 'The type of cookie cutter (project or dashboard)';
COMMENT ON COLUMN cookie_cutters.project_type_id IS 'The project type associated with the cookie cutter';
COMMENT ON COLUMN cookie_cutters.url IS 'The git URL to the cookie cutter';

GRANT SELECT ON cookie_cutters TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON cookie_cutters TO admin;
