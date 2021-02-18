CREATE TRIGGER validate_project_fact_value BEFORE INSERT OR UPDATE ON project_facts
    FOR EACH ROW EXECUTE PROCEDURE v1.validate_fact_value();
