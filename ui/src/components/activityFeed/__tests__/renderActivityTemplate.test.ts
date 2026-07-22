import { describe, expect, it } from 'vitest'

import type { PluginOpsLogTemplateMap } from '@/hooks/usePluginOpsLogTemplates'
import type { OperationsLogEntry } from '@/types'

import {
  parseActivityDescription,
  renderActivityTemplate,
} from '../renderActivityTemplate'

function makeOpsEntry(
  overrides: Partial<OperationsLogEntry> = {},
): OperationsLogEntry {
  return {
    change_type: 'Configured',
    description: '',
    display_name: 'Alex S',
    email_address: 'alexs@aweber.com',
    environment: 'production',
    id: 1,
    occurred_at: '2026-05-12T02:24:59.841Z',
    performed_by: 'alexs',
    project_id: 1,
    project_name: 'ai-content',
    recorded_at: '2026-05-12T02:24:59.841Z',
    recorded_by: 'alexs',
    type: 'OperationsLogEntry',
    version: 'v1.2.3',
    ...overrides,
  }
}

function makeTemplateMap(
  byKey: Record<string, Record<string, { label: string }>>,
): PluginOpsLogTemplateMap {
  return {
    get(pluginSlug, action) {
      const slot = pluginSlug ? byKey[pluginSlug] : undefined
      if (!slot) return undefined
      return slot[action ?? ''] ?? slot['']
    },
  }
}

describe('parseActivityDescription', () => {
  it('returns null for plain text descriptions', () => {
    expect(parseActivityDescription('deployed v1.0.0 to prod')).toBeNull()
  })

  it('returns null for empty/null/undefined input', () => {
    expect(parseActivityDescription(null)).toBeNull()
    expect(parseActivityDescription(undefined)).toBeNull()
    expect(parseActivityDescription('')).toBeNull()
    expect(parseActivityDescription('   ')).toBeNull()
  })

  it('returns null for malformed JSON', () => {
    expect(parseActivityDescription('{not valid json')).toBeNull()
  })

  it('returns null for JSON arrays', () => {
    expect(parseActivityDescription('[1,2,3]')).toBeNull()
  })

  it('returns null when plugin_slug is missing', () => {
    expect(parseActivityDescription('{"action":"set"}')).toBeNull()
  })

  it('returns null when plugin_slug is not a string', () => {
    expect(parseActivityDescription('{"plugin_slug":42}')).toBeNull()
  })

  it('returns parsed payload when plugin_slug is a string', () => {
    const result = parseActivityDescription(
      '{"plugin_slug":"aws-ssm","action":"set","key":"DATABASE_URL"}',
    )
    expect(result).toEqual({
      action: 'set',
      payload: {
        action: 'set',
        key: 'DATABASE_URL',
        plugin_slug: 'aws-ssm',
      },
      pluginSlug: 'aws-ssm',
    })
  })

  it('omits action when not a string', () => {
    const result = parseActivityDescription(
      '{"plugin_slug":"aws-ssm","action":null}',
    )
    expect(result?.action).toBeUndefined()
    expect(result?.pluginSlug).toBe('aws-ssm')
  })

  it('trims leading whitespace before checking for JSON', () => {
    expect(parseActivityDescription('   {"plugin_slug":"x"}')).not.toBeNull()
  })

  it('returns null for JSON null', () => {
    expect(parseActivityDescription('null')).toBeNull()
  })
})

describe('renderActivityTemplate', () => {
  it('returns null when description is not JSON', () => {
    const templates = makeTemplateMap({})
    const entry = makeOpsEntry({ description: 'plain text' })
    expect(renderActivityTemplate(entry, templates)).toBeNull()
  })

  it('returns null when plugin has no matching template', () => {
    const templates = makeTemplateMap({})
    const entry = makeOpsEntry({
      description: '{"plugin_slug":"unknown","action":"set"}',
    })
    expect(renderActivityTemplate(entry, templates)).toBeNull()
  })

  it('renders the template substituting display values', () => {
    const templates = makeTemplateMap({
      'aws-ssm': {
        set: { label: '{{performer}} set {{key}} in {{environment}}' },
      },
    })
    const entry = makeOpsEntry({
      description:
        '{"plugin_slug":"aws-ssm","action":"set","key":"DATABASE_URL"}',
      environment: 'staging',
      performed_by: 'alexs',
    })
    expect(renderActivityTemplate(entry, templates)).toBe(
      'alexs set DATABASE_URL in staging',
    )
  })

  it('falls back to recorded_by when performed_by is absent', () => {
    const templates = makeTemplateMap({
      'aws-ssm': { '': { label: '{{performer}}' } },
    })
    const entry = makeOpsEntry({
      description: '{"plugin_slug":"aws-ssm"}',
      performed_by: undefined as never,
      recorded_by: 'alexs',
    })
    expect(renderActivityTemplate(entry, templates)).toBe('alexs')
  })

  it('renders templates that reference entry fields like version', () => {
    const templates = makeTemplateMap({
      github: { deploy: { label: 'released {{version}}' } },
    })
    const entry = makeOpsEntry({
      description: '{"plugin_slug":"github","action":"deploy"}',
      version: 'v2.1.0',
    })
    expect(renderActivityTemplate(entry, templates)).toBe('released v2.1.0')
  })
})
