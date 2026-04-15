/**
 * Base fields that are part of all Node-derived models (Team, Environment,
 * ProjectType) and should not be treated as dynamic/blueprint fields.
 */
export const NODE_BASE_FIELDS = [
  'name',
  'slug',
  'description',
  'icon',
  'label_color',
  'organization',
  'organization_slug',
  'created_at',
  'updated_at',
  'relationships',
]

export const NODE_BASE_FIELDS_SET = new Set(NODE_BASE_FIELDS)

// Re-export under model-specific names for clarity in imports
export const TEAM_BASE_FIELDS = [...NODE_BASE_FIELDS, 'id']
export const TEAM_BASE_FIELDS_SET = new Set(TEAM_BASE_FIELDS)

export const ENVIRONMENT_BASE_FIELDS = [...NODE_BASE_FIELDS, 'sort_order', 'id']
export const ENVIRONMENT_BASE_FIELDS_SET = new Set(ENVIRONMENT_BASE_FIELDS)

export const PROJECT_TYPE_BASE_FIELDS = [...NODE_BASE_FIELDS, 'id']
export const PROJECT_TYPE_BASE_FIELDS_SET = new Set(PROJECT_TYPE_BASE_FIELDS)

export const PROJECT_BASE_FIELDS = [
  ...NODE_BASE_FIELDS,
  'team',
  'team_slug',
  'id',
  'project_type',
  'project_types',
  'environments',
  'links',
  'identifiers',
  'url',
]
export const PROJECT_BASE_FIELDS_SET = new Set(PROJECT_BASE_FIELDS)
