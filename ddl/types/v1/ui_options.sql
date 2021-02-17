SET search_path=v1;

CREATE TYPE ui_options AS ENUM ('display-as-badge', 'hide');

COMMENT ON TYPE ui_options IS 'Used to provide guidance to the UI for rendering the fact type';
