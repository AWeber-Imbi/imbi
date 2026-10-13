import { describe, expect, it, vi } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'

import { SecretDialog } from '../SecretDialog'

const renderDialog = (onSubmit: (values: Record<string, unknown>) => void) =>
  render(
    <SecretDialog
      description="A dialog"
      fields={[{ kind: 'json', label: 'Configuration', name: 'config' }]}
      isPending={false}
      onClose={vi.fn()}
      onSubmit={onSubmit}
      title="New provider"
    />,
  )

describe('SecretDialog', () => {
  it.each([
    ['[]', 'Configuration must be a JSON object'],
    ['"text"', 'Configuration must be a JSON object'],
    ['null', 'Configuration must be a JSON object'],
    ['{', 'Configuration is not valid JSON'],
  ])('refuses %s', (value, message) => {
    const onSubmit = vi.fn()
    renderDialog(onSubmit)
    fireEvent.change(screen.getByLabelText('Configuration'), {
      target: { value },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByText(message)).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('sends a JSON object', () => {
    const onSubmit = vi.fn()
    renderDialog(onSubmit)
    fireEvent.change(screen.getByLabelText('Configuration'), {
      target: { value: '{"region": "us-east-1"}' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({
      config: { region: 'us-east-1' },
    })
  })
})
