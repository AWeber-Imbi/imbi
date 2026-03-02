/**
 * Base fields that are part of the core Team model and should not
 * be treated as dynamic/blueprint fields.
 */
export const TEAM_BASE_FIELDS = [
  'name', 'slug', 'description', 'icon',
  'organization', 'organization_slug', 'created_at', 'last_modified_at',
]

export const TEAM_BASE_FIELDS_SET = new Set(TEAM_BASE_FIELDS)
