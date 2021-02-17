SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_type_enums (
  id                 SERIAL                    NOT NULL  PRIMARY KEY,
  created_at         TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by         TEXT                      NOT NULL,
  last_modified_at   TIMESTAMP WITH TIME ZONE,
  last_modified_by   TEXT,
  fact_type_id       INTEGER                   NOT NULL,
  icon_class         TEXT                      NOT NULL  DEFAULT 'fas check',
  value              TEXT                      NOT NULL,
  score              INTEGER                   CONSTRAINT valid_score CHECK (score IS NOT NULL AND score BETWEEN 0 AND 100)  DEFAULT 0,
  FOREIGN KEY (fact_type_id) REFERENCES project_fact_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON TABLE project_fact_type_enums IS 'Defines the values that are used in a column for project health score';
COMMENT ON COLUMN project_fact_type_enums.id IS 'The surrogate ID for the fact type option';
COMMENT ON COLUMN project_fact_type_enums.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_type_enums.created_by IS 'The user created the record';
COMMENT ON COLUMN project_fact_type_enums.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_type_enums.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_fact_type_enums.fact_type_id IS 'The fact type the option is for';
COMMENT ON COLUMN project_fact_type_enums.value IS 'One possible value for the fact type';
COMMENT ON COLUMN project_fact_type_enums.score IS 'The score for this value, with a maximum value of 100';

GRANT SELECT ON project_fact_type_enums TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_type_enums TO admin;
