SET search_path=v1, pg_catalog;

CREATE FUNCTION maintain_group_membership_from_ldap_groups(IN in_username TEXT, IN in_groups TEXT[]) RETURNS TEXT[]
       LANGUAGE plpgsql
       SECURITY DEFINER
AS $$
DECLARE
  dn          TEXT;
  group_name  TEXT;
  group_names TEXT[];
BEGIN
  FOREACH dn IN ARRAY in_groups
  LOOP
    group_name := v1.group_name_from_ldap_dn(dn);

    -- Ensure the group exist in the v1.groups table
    INSERT INTO v1.groups (name, group_type, external_id)
         VALUES (group_name, 'ldap', dn)
             ON CONFLICT ("name") DO NOTHING;

    -- Insure thr group and user combo exists
    INSERT INTO v1.group_members ("group", username)
         VALUES (group_name, in_username)
             ON CONFLICT DO NOTHING;
  END LOOP;

    WITH groups AS (SELECT unnest(in_groups) AS "name")
  SELECT array_agg(v1.group_name_from_ldap_dn(groups.name))
    INTO group_names
    FROM groups
   ORDER BY group_name;

  -- Delete any LDAP group memberships not passed in
  DELETE FROM v1.group_members
        WHERE username = username
          AND "group" IN (SELECT "name"
                            FROM v1.groups
                           WHERE group_type = 'ldap'
                             AND "name" NOT IN (SELECT unnest(group_names)));

  -- Return the group names
  RETURN group_names;
END;
$$;
