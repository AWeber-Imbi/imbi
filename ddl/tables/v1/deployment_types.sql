SET search_path=v1;

CREATE TABLE IF NOT EXISTS deployment_types (
  "name"      TEXT NOT NULL PRIMARY KEY,
  created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modified_at TIMESTAMP WITH TIME ZONE,
  description TEXT,
  icon_class  TEXT NOT NULL DEFAULT 'fas fa-box'
);

COMMENT ON TABLE deployment_types IS 'Types of project deployment systems';
COMMENT ON COLUMN deployment_types.name IS 'Deployment Type name';
COMMENT ON COLUMN deployment_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN deployment_types.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN deployment_types.description IS 'Description of the deployment type';
COMMENT ON COLUMN deployment_types.icon_class IS 'Font Awesome UI icon class';

GRANT SELECT ON deployment_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON deployment_types TO admin;
