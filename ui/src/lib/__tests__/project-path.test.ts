import { describe, expect, it } from 'vitest'

import { parseProjectPath, projectPath } from '@/lib/project-path'

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

  it('encodes URL delimiters in the slug', () => {
    expect(projectPath({ id: ID, slug: 'a/b#c?d' })).toBe(
      `/projects/a%2Fb%23c%3Fd/${ID}`,
    )
  })
})

describe('parseProjectPath', () => {
  it('reads the slug form', () => {
    expect(parseProjectPath(`/projects/aweber-ui/${ID}/documents/d1`)).toEqual({
      projectId: ID,
      rest: ['documents', 'd1'],
      slug: 'aweber-ui',
    })
  })

  it('round-trips a slug with URL delimiters', () => {
    const slug = 'a/b#c?d'
    expect(parseProjectPath(projectPath({ id: ID, slug }, 'settings'))).toEqual(
      { projectId: ID, rest: ['settings'], slug },
    )
  })

  it('reads the legacy ID-only form', () => {
    expect(parseProjectPath(`/projects/${ID}`)).toEqual({
      projectId: ID,
      rest: [],
    })
  })

  it('reads the legacy ID-first form with a tab', () => {
    expect(parseProjectPath(`/projects/${ID}/operations-log`)).toEqual({
      projectId: ID,
      rest: ['operations-log'],
    })
  })
})
