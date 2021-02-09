SET search_path=v1;

CREATE TYPE data_type AS ENUM ('boolean', 'date', 'decimal', 'integer', 'string', 'timestamp');

COMMENT ON TYPE data_type IS 'Used to indicate the data type for a fact type';
