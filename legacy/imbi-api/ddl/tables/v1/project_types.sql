SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_types (
  id                    SERIAL                    NOT NULL  PRIMARY KEY,
  created_at            TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by            TEXT                      NOT NULL,
  last_modified_at      TIMESTAMP WITH TIME ZONE,
  last_modified_by      TEXT,
  "name"                TEXT                      NOT NULL,
  slug                  TEXT                      NOT NULL,
  plural_name           TEXT                      NOT NULL,
  description           TEXT,
  icon_class            TEXT                                DEFAULT 'fas fa-box',
  environment_urls      BOOLEAN                   NOT NULL  DEFAULT false,
  gitlab_project_prefix TEXT
);

CREATE UNIQUE INDEX project_types_name ON project_types (name);

COMMENT ON TABLE project_types IS 'Project Types';
COMMENT ON COLUMN project_types.id IS 'Surrogate key for URLs and linking';
COMMENT ON COLUMN project_types.name IS 'The project type (API, Consumer, Database, etc)';
COMMENT ON COLUMN project_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_types.created_by IS 'The user created the record';
COMMENT ON COLUMN project_types.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_types.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_types.plural_name IS 'Name to show when displaying plural values';
COMMENT ON COLUMN project_types.slug IS 'Slug used when creating namespace URLs';
COMMENT ON COLUMN project_types.description IS 'Project Type Description';
COMMENT ON COLUMN project_types.icon_class IS 'Font Awesome UI icon class';
COMMENT ON COLUMN project_types.environment_urls IS 'Indicates projects of this type have per-environment URLs';
COMMENT ON COLUMN project_types.gitlab_project_prefix IS 'Path prefix to use when creating projects of this type in GitLab';

GRANT SELECT ON project_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_types TO admin;
