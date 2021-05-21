SET search_path=v1;

CREATE TYPE change_type
         AS ENUM ('Configured',
                  'Decommissioned',
                  'Deployed',
                  'Migrated',
                  'Provisioned',
                  'Restarted',
                  'Rolled Back',
                  'Scaled',
                  'Upgraded');

COMMENT ON TYPE change_type IS 'Used in the operations log to detail the type of change being logged';
