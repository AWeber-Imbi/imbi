SET search_path=v1, pg_catalog;

CREATE FUNCTION group_name_from_ldap_dn(IN in_name TEXT, OUT name TEXT) AS $$
  SELECT substring(in_name FROM E'^[A-Za-z]+=([A-Za-z0-9\ _-]+),.*') AS name
$$ LANGUAGE sql SECURITY DEFINER;

COMMENT ON FUNCTION group_name_from_ldap_dn(IN in_name TEXT, OUT name TEXT) IS 'Extracts the name of a group from a LDAP DN';
