SET search_path=v1, public;

CREATE TABLE IF NOT EXISTS authentication_tokens (
  token         UUID                      NOT NULL  PRIMARY KEY DEFAULT uuid_generate_v4(),
  username      TEXT                      NOT NULL,
  name          TEXT                      NOT NULL,
  created_at    TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  expires_at    TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP + interval '1 year',
  last_used_at  TIMESTAMP WITH TIME ZONE,
  FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE ON UPDATE CASCADE);

COMMENT ON TABLE authentication_tokens IS 'User created authentication tokens for interacting with the API';
COMMENT ON COLUMN authentication_tokens.token IS 'The authentication token value';
COMMENT ON COLUMN authentication_tokens.name IS 'A name to describe the tokens intended use';
COMMENT ON COLUMN authentication_tokens.username IS 'The username used to login to Imbi referencing v1.users.username';
COMMENT ON COLUMN authentication_tokens.created_at IS 'When the token was created';
COMMENT ON COLUMN authentication_tokens.expires_at IS 'When the token expires';
COMMENT ON COLUMN authentication_tokens.last_used_at IS 'When the token expires';

CREATE INDEX authentication_tokens_username ON authentication_tokens (username);

GRANT SELECT ON authentication_tokens TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON authentication_tokens TO writer;
