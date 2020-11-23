SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS teams (
  "name"      TEXT NOT NULL PRIMARY KEY,
  created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modified_at TIMESTAMP WITH TIME ZONE,
  slug        TEXT NOT NULL UNIQUE,
  icon_class  TEXT NOT NULL,
  "group"     TEXT,
  FOREIGN KEY ("group") REFERENCES v1.groups (name) ON DELETE CASCADE ON UPDATE CASCADE
);

COMMENT ON TABLE teams IS 'Organizational Teams';
COMMENT ON COLUMN teams.name IS 'Team name';
COMMENT ON COLUMN teams.created_at IS 'When the record was created at';
COMMENT ON COLUMN teams.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN teams.slug IS 'Team path slug / abbreviation';
COMMENT ON COLUMN teams.icon_class IS 'Font Awesome UI icon class';
COMMENT ON COLUMN teams.group IS 'Optional group that is associated with the team';

GRANT SELECT ON teams TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON teams TO admin;
