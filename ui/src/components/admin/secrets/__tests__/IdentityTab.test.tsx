import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  deleteWorkloadIdentity,
  getWorkloadIdentity,
  listAgents,
  listAIProviders,
  listIdentitySourceTypes,
  putWorkloadIdentity,
} from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'
import type { Agent, AIProvider } from '@/types'

import { IdentityTab } from '../IdentityTab'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  deleteWorkloadIdentity: vi.fn(),
  getWorkloadIdentity: vi.fn(),
  listAgents: vi.fn(),
  listAIProviders: vi.fn(),
  listIdentitySourceTypes: vi.fn(),
  putWorkloadIdentity: vi.fn(),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => true,
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
    vi.mocked(listAgents).mockResolvedValue([
      { id: 'agent-1', name: 'Ops helper' } as Agent,
    ])
    vi.mocked(listAIProviders).mockResolvedValue([
      { driver: 'openai', id: 'prov-1', name: 'OpenAI' } as AIProvider,
      { driver: 'bedrock', id: 'prov-2', name: 'Bedrock' } as AIProvider,
    ])
  })

  it('sets an identity source', async () => {
    vi.mocked(getWorkloadIdentity).mockResolvedValue(null)
    render(<IdentityTab orgId="org-1" orgSlug="acme" />)
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
    render(<IdentityTab orgId="org-1" orgSlug="acme" />)
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

  it('shows the ids and the vendor values', async () => {
    vi.mocked(getWorkloadIdentity).mockResolvedValue(SOURCE)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<IdentityTab orgId="org-1" orgSlug="acme" />)
    expect(await screen.findByText('imbi:org-1')).toBeInTheDocument()
    expect(await screen.findByText('Ops helper')).toBeInTheDocument()
    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
    expect(screen.queryByText('Bedrock')).toBeNull()

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Copy the vendor values of Ops helper',
      }),
    )
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining('request_tags.imbi_agent == "agent-1"'),
      ),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Copy the vendor values of OpenAI' }),
    )
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining('openai.imbi_ai_provider = prov-1'),
      ),
    )
  })
})
