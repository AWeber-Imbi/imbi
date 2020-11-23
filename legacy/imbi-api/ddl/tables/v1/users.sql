SET search_path=v1;

CREATE TABLE IF NOT EXISTS users (
  username      TEXT                     NOT NULL PRIMARY KEY,
  created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at  TIMESTAMP WITH TIME ZONE,
  user_type     entity_type              NOT NULL DEFAULT 'internal',
  external_id   TEXT                     CONSTRAINT nullable_external_id
                                              CHECK ((external_id IS NOT NULL AND user_type <> 'internal') OR
                                                     (external_id IS NULL and user_type = 'internal')),
  email_address TEXT                     NOT NULL UNIQUE,
  display_name  TEXT                     NOT NULL,
  password      TEXT                     CONSTRAINT nullable_password
                                              CHECK ((password IS NOT NULL AND user_type = 'internal') OR
                                                     (password IS NULL and user_type <> 'internal'))
);

CREATE UNIQUE INDEX users_external_id ON users (external_id) WHERE external_id IS NOT NULL;

COMMENT ON COLUMN users.username IS 'The username used to login to Imbi';
COMMENT ON COLUMN users.created_at IS 'When the record was created at';
COMMENT ON COLUMN users.last_seen_at IS 'When the most recent request occurred at';
COMMENT ON COLUMN users.user_type IS 'Indicates if the user is managed by Imbi or externally via LDAP (or other system)';
COMMENT ON COLUMN users.external_id IS 'If the user is externally managed, the ID in the external system';
COMMENT ON COLUMN users.email_address IS 'The email address for the user';
COMMENT ON COLUMN users.display_name IS 'The value to display when referencing the user';
COMMENT ON COLUMN users.password IS 'The password for the user when the user is internally managed';

GRANT SELECT ON users TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON users TO writer;


