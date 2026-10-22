import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import { CapabilityRow } from '../CapabilityRow'

const baseProps = {
  assignedTypeSlugs: [],
  description: 'Gateway-dispatched sync from webhook deliveries.',
  enabled: true,
  kind: 'webhook-actions',
  label: 'Webhook actions',
  onAssignmentChange: vi.fn(),
  onOptionChange: vi.fn(),
  onToggle: vi.fn(),
  options: [],
  optionValues: {},
  projectScoped: false,
  projectTypes: [],
}

describe('CapabilityRow webhook delivery URLs', () => {
  it('renders a copyable delivery URL for each webhook', () => {
    render(
      <CapabilityRow
        {...baseProps}
        webhookUrls={[
          {
            name: 'GitHub Events',
            url: 'https://imbi.example.com/gateway/notifications/abc123',
          },
        ]}
      />,
    )
    expect(screen.getByText('Delivery URL')).toBeInTheDocument()
    expect(
      screen.getByText('https://imbi.example.com/gateway/notifications/abc123'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /copy/i })).toBeInTheDocument()
  })

  it('labels each URL when the integration has multiple webhooks', () => {
    render(
      <CapabilityRow
        {...baseProps}
        webhookUrls={[
          {
            name: 'GitHub Events',
            url: 'https://imbi.example.com/gateway/notifications/abc123',
          },
          {
            name: 'GitHub Releases',
            url: 'https://imbi.example.com/gateway/notifications/def456',
          },
        ]}
      />,
    )
    expect(screen.getByText('Delivery URLs')).toBeInTheDocument()
    expect(screen.getByText('GitHub Events')).toBeInTheDocument()
    expect(screen.getByText('GitHub Releases')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /copy/i })).toHaveLength(2)
  })

  it('copies the URL to the clipboard', () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(
      <CapabilityRow
        {...baseProps}
        webhookUrls={[
          {
            name: 'GitHub Events',
            url: 'https://imbi.example.com/gateway/notifications/abc123',
          },
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /copy/i }))
    expect(writeText).toHaveBeenCalledWith(
      'https://imbi.example.com/gateway/notifications/abc123',
    )
    expect(screen.getByRole('button', { name: /copied/i })).toBeInTheDocument()
  })

  it('shows a create-webhook hint when no webhooks exist', () => {
    render(<CapabilityRow {...baseProps} webhookUrls={[]} />)
    expect(
      screen.getByText(/No webhooks are configured for this integration/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Admin → Webhooks/ }),
    ).toHaveAttribute('href', '/admin/webhooks')
  })

  it('omits the section when webhookUrls is not provided', () => {
    render(<CapabilityRow {...baseProps} />)
    expect(screen.queryByText(/Delivery URL/)).not.toBeInTheDocument()
  })
})

describe('CapabilityRow project-type assignment', () => {
  const scopedProps = {
    ...baseProps,
    assignedTypeSlugs: ['api'],
    projectScoped: true,
    projectTypes: [
      { name: 'API', slug: 'api' },
      { name: 'Consumer', slug: 'consumer' },
    ],
  }

  it('blocks edits while assignmentDisabled is set', () => {
    const onAssignmentChange = vi.fn()
    render(
      <CapabilityRow
        {...scopedProps}
        assignmentDisabled
        onAssignmentChange={onAssignmentChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    const chip = screen.getByRole('button', { name: 'Consumer' })
    expect(chip).toBeDisabled()
    expect(screen.getByRole('button', { name: /clear all/i })).toBeDisabled()
    fireEvent.click(chip)
    expect(onAssignmentChange).not.toHaveBeenCalled()
  })

  it('sends the new slug list when enabled', () => {
    const onAssignmentChange = vi.fn()
    render(
      <CapabilityRow
        {...scopedProps}
        onAssignmentChange={onAssignmentChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Consumer' }))
    expect(onAssignmentChange).toHaveBeenCalledWith(['api', 'consumer'])
  })
})
