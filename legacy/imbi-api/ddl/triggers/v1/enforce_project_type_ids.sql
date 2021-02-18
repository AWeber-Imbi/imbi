CREATE TRIGGER enforce_project_type_ids BEFORE INSERT OR UPDATE ON project_fact_types
    FOR EACH ROW EXECUTE PROCEDURE v1.enforce_project_type_ids();
