import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserResponse } from '@/types'

import { useHasPermission } from '../useHasPermission'

const auth = vi.hoisted(() => ({ user: null as null | UserResponse }))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => auth }))

function has(permission: string, orgSlug?: string): boolean {
  return renderHook(() => useHasPermission(permission, orgSlug)).result.current
}

// Developer in acme, read-only in beta. The union is what GET /users/me
// returns at the top level.
function twoOrgUser(is_admin = false): UserResponse {
  const membership = (slug: string, role: string, permissions: string[]) => ({
    organization_name: slug,
    organization_slug: slug,
    permissions,
    role,
  })
  return {
    display_name: 'Pat',
    email: 'pat@example.com',
    is_admin,
    organizations: [
      membership('acme', 'developer', ['agent:read', 'agent_task:manage']),
      membership('beta', 'readonly', ['agent:read']),
    ],
    permissions: ['agent:read', 'agent_task:manage'],
    user_type: 'internal',
    username: 'pat',
  }
}

describe('useHasPermission', () => {
  beforeEach(() => {
    auth.user = twoOrgUser()
  })

  it('checks the union without an organization', () => {
    expect(has('agent_task:manage')).toBe(true)
    expect(has('agent:delete')).toBe(false)
  })

  it('checks only the role in the given organization', () => {
    expect(has('agent_task:manage', 'acme')).toBe(true)
    expect(has('agent_task:manage', 'beta')).toBe(false)
    expect(has('agent:read', 'beta')).toBe(true)
  })

  it('denies an organization the user is not a member of', () => {
    expect(has('agent:read', 'gamma')).toBe(false)
  })

  it('lets an admin do anything, in member organizations only', () => {
    auth.user = twoOrgUser(true)
    expect(has('agent:delete')).toBe(true)
    expect(has('agent:delete', 'beta')).toBe(true)
    expect(has('agent:delete', 'gamma')).toBe(false)
  })

  it('denies a membership without permissions from an older API', () => {
    const user = twoOrgUser()
    delete (user.organizations[1] as { permissions?: string[] }).permissions
    auth.user = user
    expect(has('agent:read', 'beta')).toBe(false)
  })

  it('denies everything without a user', () => {
    auth.user = null
    expect(has('agent:read')).toBe(false)
    expect(has('agent:read', 'acme')).toBe(false)
  })
})
