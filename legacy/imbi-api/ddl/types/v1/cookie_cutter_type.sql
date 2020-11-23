SET search_path=v1;

CREATE TYPE cookie_cutter_type AS ENUM ('project', 'dashboard');

COMMENT ON TYPE cookie_cutter_type IS 'Used to specify the type of cookie cutter in v1.cookie_cutters';
