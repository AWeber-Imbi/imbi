SET search_path=v1;

CREATE TABLE IF NOT EXISTS namespace_kpi_history (
  namespace_id          INTEGER       NOT NULL,
  scored_on             DATE          NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  project_count         INTEGER       NOT NULL,
  health_score          NUMERIC(9,2)  NOT NULL,
  total_possible_score  NUMERIC(9,2)  NOT NULL,
  total_project_score   NUMERIC(9,2)  NOT NULL,
  PRIMARY KEY (namespace_id, scored_on),
  FOREIGN KEY (namespace_id) REFERENCES namespaces (id) ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE  namespace_kpi_history IS 'Table detailing namespace stack health scores during over a regular cadence';
COMMENT ON COLUMN  namespace_kpi_history.namespace_id IS 'The namespace ID';
COMMENT ON COLUMN  namespace_kpi_history.scored_on IS 'When the record was created / score where';
COMMENT ON COLUMN  namespace_kpi_history.project_count IS 'The score value';
COMMENT ON COLUMN  namespace_kpi_history.health_score IS 'The project health score';
COMMENT ON COLUMN  namespace_kpi_history.total_possible_score IS 'The maximum possible sum of all project scores';
COMMENT ON COLUMN  namespace_kpi_history.total_project_score IS 'The sum of all project scores';

GRANT SELECT ON  namespace_kpi_history TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON  namespace_kpi_history TO admin;
