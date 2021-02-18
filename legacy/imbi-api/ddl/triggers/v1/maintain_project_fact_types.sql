CREATE TRIGGER maintain_project_fact_types BEFORE DELETE ON project_types
    FOR EACH ROW EXECUTE PROCEDURE v1.remove_project_type_from_project_fact_types();
