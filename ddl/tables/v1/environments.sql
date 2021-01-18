SET search_path=v1;

CREATE TABLE IF NOT EXISTS environments (
  "name"      TEXT NOT NULL PRIMARY KEY,
  created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modified_at TIMESTAMP WITH TIME ZONE,
  description TEXT,
  text_class  TEXT,
  icon_class  TEXT DEFAULT 'fas fa-mountain'
);

COMMENT ON TABLE environments IS 'Operational Environments';
COMMENT ON COLUMN environments.name IS 'Environment name';
COMMENT ON COLUMN environments.created_at IS 'When the record was created at';
COMMENT ON COLUMN environments.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN environments.text_class IS 'CSS class for when the value is displayed';
COMMENT ON COLUMN environments.icon_class IS 'CSS icon class';

GRANT SELECT ON environments TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON environments TO admin;
