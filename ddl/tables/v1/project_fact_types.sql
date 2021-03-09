SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_types (
  id                   SERIAL                    NOT NULL  PRIMARY KEY,
  created_at           TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by           TEXT                      NOT NULL,
  last_modified_at     TIMESTAMP WITH TIME ZONE,
  last_modified_by     TEXT,
  project_type_ids     INTEGER[],
  name                 TEXT                      NOT NULL,
  fact_type            fact_type                 NOT NULL  DEFAULT 'free-form',
  data_type            data_type                 NOT NULL  DEFAULT 'string',
  description          TEXT,
  ui_options           TEXT[]                    CONSTRAINT valid_ui_options CHECK (ui_options <@ ARRAY['display-as-badge', 'display-as-percentage', 'hidden']),
  weight               INTEGER                   CONSTRAINT valid_weight CHECK (weight IS NOT NULL AND weight BETWEEN 0 AND 100)  DEFAULT 0
);

CREATE UNIQUE INDEX unique_name_and_project_type_ids ON v1.project_fact_types (name, project_type_ids);

COMMENT ON TABLE project_fact_types IS 'Defines the types that are used for project health score';
COMMENT ON COLUMN project_fact_types.id IS 'Surrogate key for URLs and linking';
COMMENT ON COLUMN project_fact_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_types.created_by IS 'The user created the record';
COMMENT ON COLUMN project_fact_types.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_types.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_fact_types.project_type_ids IS 'One or more project types that are associated with this fact type, if null applies to all projects';
COMMENT ON COLUMN project_fact_types.name IS 'The fact type name';
COMMENT ON COLUMN project_fact_types.fact_type IS 'Indicates if the fact type value is free-form, is constrained to an enum, or is constrained to a numeric value within a range';
COMMENT ON COLUMN project_fact_types.data_type IS 'While the values are stored as text, the data type is used to coerce the value to the correct datatype in processing and display';
COMMENT ON COLUMN project_fact_types.description IS 'Describes the purpose of the fact type and expands upon the name to provide additional context';
COMMENT ON COLUMN project_fact_types.ui_options IS 'An array of one or more values for the UI that indicate how to display fact type values for this fact type';
COMMENT ON COLUMN project_fact_types.weight IS 'The weight from 0 to 100 of the total score for a project. Total weight should across all types for a project type should not exceed 100.';

GRANT SELECT ON project_fact_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_types TO admin;
