SET search_path=v1;

CREATE TABLE IF NOT EXISTS group_members (
  "group"   TEXT  NOT NULL,
  username TEXT  NOT NULL,
  PRIMARY KEY ("group", username),
  FOREIGN KEY ("group") REFERENCES v1.groups (name) ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (username) REFERENCES v1.users (username) ON DELETE CASCADE ON UPDATE CASCADE);

COMMENT ON TABLE group_members IS 'Group Memberships';

COMMENT ON COLUMN group_members.group IS 'The group name the user is a member to';
COMMENT ON COLUMN group_members.username IS 'The user that is a member of the group';
