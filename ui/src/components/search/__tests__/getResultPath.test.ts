import { describe, expect, it } from 'vitest'

import type { SearchResult } from '@/api/endpoints'

import { getResultPath } from '../getResultPath'

function result(overrides: Partial<SearchResult>): SearchResult {
  return {
    attribute: 'description',
    chunk_text: '…',
    distance: 0.1,
    node_id: 'node-1',
    node_label: 'Project',
    ...overrides,
  }
}

describe('getResultPath', () => {
  it('routes a Project by id', () => {
    expect(getResultPath(result({ node_label: 'Project' }))).toBe(
      '/projects/node-1',
    )
  })

  it('routes a Document under its parent project', () => {
    const path = getResultPath(
      result({ node_label: 'Document', project_id: 'proj-9' }),
    )
    expect(path).toBe('/projects/proj-9/documents/node-1')
  })

  it('routes a Release under its parent project', () => {
    const path = getResultPath(
      result({ node_label: 'Release', project_id: 'proj-9' }),
    )
    expect(path).toBe('/projects/proj-9/releases/node-1')
  })

  it('returns null for a Document with no project_id', () => {
    expect(getResultPath(result({ node_label: 'Document' }))).toBeNull()
  })

  it('returns null for a Release with no project_id', () => {
    expect(getResultPath(result({ node_label: 'Release' }))).toBeNull()
  })

  it('routes admin node types by slug', () => {
    const cases: Array<[string, string]> = [
      ['Team', 'teams'],
      ['Environment', 'environments'],
      ['ProjectType', 'project-types'],
      ['DocumentTemplate', 'document-templates'],
      ['LinkDefinition', 'link-definitions'],
      ['Organization', 'organizations'],
      ['Blueprint', 'blueprints'],
      ['Role', 'roles'],
    ]
    for (const [nodeLabel, section] of cases) {
      const path = getResultPath(
        result({ node_label: nodeLabel, slug: 'the-slug' }),
      )
      expect(path).toBe(`/admin/${section}/the-slug`)
    }
  })

  it('returns null for an admin node type missing its slug', () => {
    expect(getResultPath(result({ node_label: 'Team' }))).toBeNull()
  })

  it('returns null for routeless types (Tag, Comment, Component)', () => {
    for (const nodeLabel of ['Tag', 'Comment', 'Component']) {
      expect(
        getResultPath(result({ node_label: nodeLabel, slug: 'x' })),
      ).toBeNull()
    }
  })
})
