import { formatDistanceToNow } from 'date-fns'

import type { ProjectSchemaSection } from '@/api/endpoints'
import type { Project } from '@/types'

export const COLOR_TEXT: Record<string, string> = {
  amber: 'text-amber-600',
  blue: 'text-blue-600',
  gray: 'text-gray-500',
  green: 'text-green-600',
  grey: 'text-gray-500',
  red: 'text-red-600',
  yellow: 'text-yellow-600',
}

/** Format a snake_case or camelCase key as a readable label */
export const WORD_OVERRIDES: Record<string, string> = {
  aws: 'AWS',
  ci: 'CI',
  github: 'GitHub',
  gitlab: 'GitLab',
  sonarqube: 'SonarQube',
}

export function formatFieldKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .split(' ')
    .map((w) => WORD_OVERRIDES[w.toLowerCase()] ?? w)
    .join(' ')
}

/** Render a field value as a display string using schema metadata for formatting. */
export function formatFieldValue(
  value: unknown,
  def?: {
    format?: null | string
    maximum?: null | number
    minimum?: null | number
    type?: null | string
  },
): null | string {
  if (value === null || value === undefined || value === '') return null

  const raw = String(value).trim()
  if (raw === '') return null

  const type = def?.type
  const format = def?.format

  // Booleans — stored as strings "true"/"false" from Neo4j
  if (type === 'boolean' || raw === 'true' || raw === 'false') {
    return raw === 'true' ? 'True' : 'False'
  }

  // Dates and datetimes — display as relative time
  if (format === 'date-time' || format === 'date') {
    const d = new Date(raw)
    if (!isNaN(d.getTime())) {
      return formatDistanceToNow(d, { addSuffix: true })
    }
  }

  // Integers
  if (type === 'integer') {
    const n = parseInt(raw, 10)
    if (!isNaN(n)) return n.toLocaleString()
  }

  // Numbers / floats
  if (type === 'number') {
    const n = parseFloat(raw)
    if (!isNaN(n)) {
      if (def?.minimum === 0 && def?.maximum === 100) {
        return (
          n.toLocaleString(undefined, {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2,
          }) + '%'
        )
      }
      return n.toLocaleString()
    }
  }

  if (typeof value === 'object') return JSON.stringify(value)
  return raw
}

export function resolveFieldValue(
  key: string,
  _section: ProjectSchemaSection,
  project: Project,
): unknown {
  // Determine if this section is environment-scoped by checking if any
  // of the project's environments has a matching value for this key.
  // The API already filtered sections to only applicable envs, so if the
  // project-level value is absent, check environment objects.
  const projectValue = project[key]
  if (
    projectValue !== null &&
    projectValue !== undefined &&
    projectValue !== ''
  ) {
    return projectValue
  }
  // Fall back to environment objects (e.g. url, or any env-scoped field)
  for (const env of project.environments || []) {
    const envVal = (env as Record<string, unknown>)[key]
    if (envVal !== null && envVal !== undefined && envVal !== '') {
      return envVal
    }
  }
  return undefined
}
