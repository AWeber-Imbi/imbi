import { beforeEach, describe, expect, it, vi } from 'vitest'

import { buildDiffPatch } from '@/lib/json-patch'
import { fireEvent, render, screen } from '@/test/utils'
import type { Webhook } from '@/types'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteUpload: vi.fn(),
  listIntegrations: vi.fn(() => Promise.resolve([])),
  uploadFile: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

// Mirrors WebhookResponse, which has no `secret` field.
const webhook = (overrides: Partial<Webhook> = {}): Webhook =>
  ({
    icon: null,
    id: 'wh-1',
    name: 'GitHub Push',
    notification_path: '/webhooks/acme/github-push',
    rules: [],
    slug: 'github-push',
    ...overrides,
  }) as unknown as Webhook

const save = async (onSave: ReturnType<typeof vi.fn>) => {
  const { WebhookForm } = await import('../WebhookForm')
  render(<WebhookForm onCancel={vi.fn()} onSave={onSave} webhook={webhook()} />)
  return () => fireEvent.click(screen.getByText('Save Changes'))
}

describe('WebhookForm secret handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('omits the secret when the field is left blank', async () => {
    const onSave = vi.fn()
    const submit = await save(onSave)
    submit()
    expect(onSave).toHaveBeenCalledTimes(1)
    expect('secret' in onSave.mock.calls[0][0]).toBe(false)
  })

  it('includes the secret when the field is filled in', async () => {
    const onSave = vi.fn()
    const submit = await save(onSave)
    fireEvent.change(screen.getByPlaceholderText('(unchanged)'), {
      target: { value: '  s3cret  ' },
    })
    submit()
    expect(onSave.mock.calls[0][0].secret).toBe('s3cret')
  })

  it('generates no /secret patch op for a blank secret field', async () => {
    const onSave = vi.fn()
    const submit = await save(onSave)
    fireEvent.change(screen.getByPlaceholderText('e.g., GitHub Push Events'), {
      target: { value: 'Renamed' },
    })
    submit()
    const data = onSave.mock.calls[0][0] as Record<string, unknown>
    const ops = buildDiffPatch(
      webhook() as unknown as Record<string, unknown>,
      data,
      { fields: Object.keys(data) },
    )
    expect(ops.some((op) => op.path === '/secret')).toBe(false)
    expect(ops).toContainEqual({
      op: 'replace',
      path: '/name',
      value: 'Renamed',
    })
  })
})
