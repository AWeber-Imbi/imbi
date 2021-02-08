# 8. Move optional project attributes to project facts

Date: 2021-02-07

## Status

Accepted

## Context

When the schema for Imbi was originally developed in 2018, the compliance subsection hadn't been fully considered.

As I implemented the project fact types and project fact type options as part of compliance management, it has become clear that the configuration system, data centers, deployment type, and orchestration system fields woudl be better served as project facts.

Doing so will allow for those fields to also be used as part of compliance management and scoring.

## Decision

The four fields will be removed from `v1.projects` along with all the endpoints and UI views for managing them.

`v1.project_fact_types` and `v1.project_fact_type_options` will be updated to include additional metadata such as an icon class.

In addition, `v1.project_fact_types` will be updated to make `project_type_id` nullable. When nullable, it will indicate the project fact type is applicable to all projects.

## Consequences

Data will become less structured and it will become less obvious to new users on how the system is intended to be use. Perhaps providing starter DML will allow a new user to see how they can structure their project fact types to cover their use cases.
