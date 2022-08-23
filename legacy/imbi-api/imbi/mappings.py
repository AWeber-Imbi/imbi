"""
OpenSearch Mapping Management

"""
FACT_DATA_TYPES = {
    'boolean': 'boolean',
    'date': 'date',
    'decimal': 'float',
    'integer': 'integer',
    'string': 'text',
    'timestamp': 'date'
}

PROJECT = {
    'id': {'type': 'integer'},
    'created_at': {'type': 'date'},
    'created_by': {'type': 'text'},
    'last_modified_at': {'type': 'date'},
    'last_modified_by': {'type': 'text'},
    'namespace': {'type': 'text'},
    'namespace_slug': {'type': 'text'},
    'project_type': {'type': 'text'},
    'project_type_slug': {'type': 'text'},
    'name': {'type': 'text'},
    'slug': {'type': 'text'},
    'description': {'type': 'text'},
    'environments': {'type': 'text'},
    'archived': {'type': 'boolean'},
    'gitlab_project_id': {'type': 'text'},
    'sentry_project_slug': {'type': 'text'},
    'sonarqube_project_key': {'type': 'text'},
    'pagerduty_service_id': {'type': 'text'},
    'project_score': {'type': 'integer'}
}
