SET search_path=v1;

CREATE TABLE IF NOT EXISTS groups (
  "name"            TEXT                      NOT NULL  PRIMARY KEY,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL  DEFAULT 'system',
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  group_type        entity_type              NOT NULL  DEFAULT 'internal',
  external_id       TEXT                     CONSTRAINT nullable_external_id
                                                  CHECK ((external_id IS NOT NULL AND group_type <> 'internal') OR
                                                         (external_id IS NULL and group_type = 'internal')),
  permissions       TEXT[]
);

CREATE UNIQUE INDEX groups_external_id ON groups (external_id) WHERE external_id IS NOT NULL;

COMMENT ON TABLE groups IS 'User Groups';

COMMENT ON COLUMN groups.name IS 'The name used to reference the group in Imbi';
COMMENT ON COLUMN groups.created_at IS 'When the record was created at';
COMMENT ON COLUMN groups.created_by IS 'The user that created the group, system if created in a LDAP sync';
COMMENT ON COLUMN groups.last_modified_at IS 'When the record was was last modified at';
COMMENT ON COLUMN groups.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN groups.group_type IS 'Indicates if the group is managed by Imbi or externally via LDAP (or other system)';
COMMENT ON COLUMN groups.external_id IS 'If the group is externally managed, the ID in the external system';
COMMENT ON COLUMN groups.permissions IS 'Array of permissions to grant members of the group';

GRANT SELECT ON groups TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON groups TO admin;
