import { describe, expect, it } from 'vitest'

import { parseProjectSegments, projectPath } from '@/lib/project-path'

const ID = 'cEsK1fmn03v323upxC0TG'

describe('projectPath', () => {
  it('puts the slug before the ID', () => {
    expect(projectPath({ id: ID, slug: 'aweber-ui' })).toBe(
      `/projects/aweber-ui/${ID}`,
    )
    expect(projectPath({ id: ID, slug: 'aweber-ui' }, 'documents', 'd1')).toBe(
      `/projects/aweber-ui/${ID}/documents/d1`,
    )
  })
})

describe('parseProjectSegments', () => {
  it('reads the slug form', () => {
    expect(parseProjectSegments(['aweber-ui', ID, 'documents', 'd1'])).toEqual({
      projectId: ID,
      rest: ['documents', 'd1'],
      slug: 'aweber-ui',
    })
  })

  it('reads the legacy ID-only form', () => {
    expect(parseProjectSegments([ID])).toEqual({
      projectId: ID,
      rest: [],
    })
  })

  it('reads the legacy ID-first form with a tab', () => {
    expect(parseProjectSegments([ID, 'operations-log'])).toEqual({
      projectId: ID,
      rest: ['operations-log'],
    })
  })
})
