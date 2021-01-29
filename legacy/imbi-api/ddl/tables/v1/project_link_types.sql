SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_link_types (
  id                SERIAL                    NOT NULL  PRIMARY KEY,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  link_type         TEXT                      NOT NULL  UNIQUE,
  icon_class        TEXT                                DEFAULT 'fas fa-link'
);

COMMENT ON TABLE project_link_types IS 'Table of the types of links allowed for a project';
COMMENT ON COLUMN project_link_types.id IS 'Surrogate key for URLs and linking';
COMMENT ON COLUMN project_link_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_link_types.created_by IS 'The user created the record';
COMMENT ON COLUMN project_link_types.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_link_types.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_link_types.link_type IS 'The project link type';
COMMENT ON COLUMN project_link_types.icon_class IS 'Font Awesome UI icon class';

GRANT SELECT ON project_link_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_link_types TO admin;
