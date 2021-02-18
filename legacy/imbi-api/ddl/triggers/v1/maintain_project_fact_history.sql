CREATE TRIGGER maintain_project_fact_history AFTER INSERT OR UPDATE ON project_facts
    FOR EACH ROW EXECUTE PROCEDURE v1.insert_project_fact_history();
