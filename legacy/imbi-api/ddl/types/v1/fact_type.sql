SET search_path=v1;

CREATE TYPE fact_type AS ENUM ('enum', 'free-form', 'range');

COMMENT ON TYPE fact_type IS 'Used to indicate the data type for a fact type';
