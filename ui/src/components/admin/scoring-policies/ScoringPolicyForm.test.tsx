import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { ScoringPolicyForm } from './ScoringPolicyForm'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  listEnvironments: vi
    .fn()
    .mockResolvedValue([{ name: 'Production', slug: 'production' }]),
  listLinkDefinitions: vi.fn().mockResolvedValue([]),
  listProjectTypes: vi.fn().mockResolvedValue([]),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/OrganizationContext', () => ({
  useOrganization: () => ({ selectedOrganization: { slug: 'acme' } }),
}))

describe('ScoringPolicyForm deployment_status', () => {
  it('saves a deployment status policy with its environment and scores', async () => {
    const onSave = vi.fn()
    render(
      <ScoringPolicyForm onCancel={vi.fn()} onSave={onSave} policy={null} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Deployment Status' }))
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Prod deploys' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: /Environment/ }))
    fireEvent.click(await screen.findByRole('option', { name: 'Production' }))
    fireEvent.change(screen.getByLabelText('Rolled back'), {
      target: { value: '10' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Policy' }))

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          category: 'deployment_status',
          environment_slug: 'production',
          slug: 'prod-deploys',
          status_score_map: {
            failed: 0,
            in_progress: 100,
            missing: 100,
            pending: 100,
            rolled_back: 10,
            success: 100,
          },
        }),
      ),
    )
  })

  it('requires an environment', () => {
    const onSave = vi.fn()
    render(
      <ScoringPolicyForm onCancel={vi.fn()} onSave={onSave} policy={null} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Deployment Status' }))
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Prod deploys' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Policy' }))
    expect(screen.getByText('Environment is required')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('saves a score in exponent form as its value', async () => {
    const onSave = vi.fn()
    render(
      <ScoringPolicyForm onCancel={vi.fn()} onSave={onSave} policy={null} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Deployment Status' }))
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Prod deploys' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: /Environment/ }))
    fireEvent.click(await screen.findByRole('option', { name: 'Production' }))
    fireEvent.change(screen.getByLabelText('Rolled back'), {
      target: { value: '1e2' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Policy' }))

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          status_score_map: expect.objectContaining({ rolled_back: 100 }),
        }),
      ),
    )
  })

  it('requires at least one score', async () => {
    const onSave = vi.fn()
    render(
      <ScoringPolicyForm onCancel={vi.fn()} onSave={onSave} policy={null} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Deployment Status' }))
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Prod deploys' },
    })
    fireEvent.click(screen.getByRole('combobox', { name: /Environment/ }))
    fireEvent.click(await screen.findByRole('option', { name: 'Production' }))
    for (const label of [
      'Success',
      'In progress',
      'Pending',
      'Failed',
      'Not deployed',
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: '' } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Create Policy' }))
    expect(screen.getByText('Enter at least one score')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })
})
