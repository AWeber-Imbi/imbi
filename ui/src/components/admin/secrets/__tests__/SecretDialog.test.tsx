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

  it('sends only the changed fields of an edit', () => {
    const onSubmit = vi.fn()
    render(
      <SecretDialog
        description="A dialog"
        fields={[
          { createOnly: true, kind: 'text', label: 'Reference', name: 'ref' },
          { kind: 'list', label: 'Fields', name: 'allowed_fields' },
          { kind: 'list', label: 'Purposes', name: 'purposes' },
          { kind: 'text', label: 'Description', name: 'description' },
          {
            group: 'usage',
            kind: 'text',
            label: 'Host',
            name: 'host',
          },
          { group: 'usage', kind: 'text', label: 'App id', name: 'app_id' },
        ]}
        isPending={false}
        onClose={vi.fn()}
        onSubmit={onSubmit}
        original={{
          allowed_fields: ['token'],
          description: 'kept',
          purposes: ['npm'],
          ref: 'secret://a/b',
          usage: { app_id: '1', host: 'github.com' },
        }}
        title="Edit binding"
      />,
    )
    expect(screen.queryByLabelText('Reference')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Fields'), {
      target: { value: '' },
    })
    fireEvent.change(screen.getByLabelText('Purposes'), {
      target: { value: 'npm, marketplace_fetch' },
    })
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('App id'), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({
      allowed_fields: [],
      purposes: ['npm', 'marketplace_fetch'],
      usage: null,
    })
  })

  it('closes an edit with no changes', () => {
    const onClose = vi.fn()
    const onSubmit = vi.fn()
    render(
      <SecretDialog
        description="A dialog"
        fields={[{ kind: 'json', label: 'Configuration', name: 'config' }]}
        isPending={false}
        onClose={onClose}
        onSubmit={onSubmit}
        original={{ config: { region: 'us-east-1' } }}
        title="Edit provider"
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })
})
