SET search_path=v1;

CREATE TYPE entity_type AS ENUM ('internal', 'ldap');

COMMENT ON TYPE entity_type IS 'Used to track the type of authentication entity is record';
