import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  deleteWorkloadIdentity,
  getWorkloadIdentity,
  listIdentitySourceTypes,
  putWorkloadIdentity,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { IdentityTab } from '../IdentityTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteWorkloadIdentity: vi.fn(),
  getWorkloadIdentity: vi.fn(),
  listIdentitySourceTypes: vi.fn(),
  putWorkloadIdentity: vi.fn(),
}))

const CONFIG = {
  region: 'us-east-1',
  role_arn: 'arn:aws:iam::123456789012:role/imbi-identity',
}
const SOURCE = {
  config: CONFIG,
  type: 'aws_sts',
  updated_at: '2026-11-06T00:00:00Z',
  updated_by: 'admin',
}

describe('IdentityTab', () => {
  beforeEach(() => {
    vi.mocked(listIdentitySourceTypes).mockResolvedValue([
      { label: 'AWS STS', type: 'aws_sts' },
    ])
    vi.mocked(putWorkloadIdentity).mockResolvedValue(SOURCE)
    vi.mocked(deleteWorkloadIdentity).mockResolvedValue(undefined)
  })

  it('sets an identity source', async () => {
    vi.mocked(getWorkloadIdentity).mockResolvedValue(null)
    render(<IdentityTab orgSlug="acme" />)
    expect(
      await screen.findByText(/Workload identity federation is off/),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Set identity source' }))
    fireEvent.click(await screen.findByLabelText('Type'))
    fireEvent.click(await screen.findByRole('option', { name: 'AWS STS' }))
    fireEvent.change(screen.getByLabelText(/Configuration/), {
      target: { value: JSON.stringify(CONFIG) },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(putWorkloadIdentity).toHaveBeenCalledWith('acme', {
        config: CONFIG,
        type: 'aws_sts',
      }),
    )
  })

  it('edits and removes the current source', async () => {
    vi.mocked(getWorkloadIdentity).mockResolvedValue(SOURCE)
    render(<IdentityTab orgSlug="acme" />)
    expect(await screen.findByText('aws_sts')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Set identity source' }),
    ).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const config = { ...CONFIG, region: 'us-west-2' }
    fireEvent.change(await screen.findByLabelText(/Configuration/), {
      target: { value: JSON.stringify(config) },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    // An edit sends the whole source: the API replaces it.
    await waitFor(() =>
      expect(putWorkloadIdentity).toHaveBeenCalledWith('acme', {
        config,
        type: 'aws_sts',
      }),
    )

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Delete the aws_sts identity source',
      }),
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deleteWorkloadIdentity).toHaveBeenCalled())
  })
})
