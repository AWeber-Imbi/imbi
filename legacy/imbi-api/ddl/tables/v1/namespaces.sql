SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS namespaces (
  id                SERIAL                    NOT NULL  PRIMARY KEY,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  "name"            TEXT                      NOT NULL  UNIQUE,
  slug              TEXT                      NOT NULL  UNIQUE,
  icon_class        TEXT                      NOT NULL,
  maintained_by     TEXT[],
  gitlab_group_name TEXT);

COMMENT ON TABLE namespaces IS 'Organizational Teams';
COMMENT ON COLUMN namespaces.id IS 'Surrogate key for URLs and linking';
COMMENT ON COLUMN namespaces.created_at IS 'When the record was created at';
COMMENT ON COLUMN namespaces.created_by IS 'The user created the record';
COMMENT ON COLUMN namespaces.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN namespaces.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN namespaces.name IS 'Team name';
COMMENT ON COLUMN namespaces.slug IS 'Team path slug';
COMMENT ON COLUMN namespaces.icon_class IS 'Font Awesome UI icon class';
COMMENT ON COLUMN namespaces.maintained_by IS 'Optional groups that have access to modify projects in the namespace';
COMMENT ON COLUMN namespaces.gitlab_group_name IS 'Optional name of the corresponding group in GitLab';

GRANT SELECT ON namespaces TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON namespaces TO admin;
