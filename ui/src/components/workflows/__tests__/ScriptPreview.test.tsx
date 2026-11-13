import { beforeEach, describe, expect, it, vi } from 'vitest'

import { previewScript } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { ScriptPreview } from '../ScriptPreview'
import { node } from './fixtures'

vi.mock('@/api/endpoints', () => ({ previewScript: vi.fn() }))

const FIELDS = [{ name: 'count', type: 'integer' }]

function renderPreview() {
  render(
    <ScriptPreview
      node={node({
        params: {
          branches: ['low', 'high'],
          code: "{'count': n, 'branch': 'high'}",
          inputs: { limit: 2, n: '{{ trigger.n }}' },
          output_fields: FIELDS,
        },
        type: 'script',
      })}
      orgSlug="acme"
    />,
  )
}

describe('ScriptPreview', () => {
  beforeEach(() => vi.mocked(previewScript).mockReset())

  it('runs the code with sample inputs and shows the result', async () => {
    vi.mocked(previewScript).mockResolvedValue({
      output: { branch: 'high', result: { count: 7 }, stdout: 'hi\n' },
      port: 1,
    })
    renderPreview()
    // A template has no sample value until the person writes one.
    const sample = screen.getByLabelText('Sample inputs')
    expect(JSON.parse((sample as HTMLTextAreaElement).value)).toEqual({
      limit: 2,
      n: null,
    })
    fireEvent.change(sample, { target: { value: '{"limit": 2, "n": 7}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run script' }))
    expect(await screen.findByText('high')).toBeInTheDocument()
    expect(screen.getByText('hi')).toBeInTheDocument()
    expect(previewScript).toHaveBeenCalledWith('acme', {
      branches: ['low', 'high'],
      code: "{'count': n, 'branch': 'high'}",
      inputs: { limit: 2, n: 7 },
      output_fields: FIELDS,
    })
  })

  it('shows the error that stopped the script', async () => {
    vi.mocked(previewScript).mockResolvedValue({
      error: 'script_error',
      message: 'ValueError: nope',
    })
    renderPreview()
    fireEvent.click(screen.getByRole('button', { name: 'Run script' }))
    expect(await screen.findByText('script_error')).toBeInTheDocument()
    expect(screen.getByText('ValueError: nope')).toBeInTheDocument()
    // A new sample clears the result of the last run.
    fireEvent.change(screen.getByLabelText('Sample inputs'), {
      target: { value: '{"n": 1}' },
    })
    await waitFor(() =>
      expect(screen.queryByText('script_error')).not.toBeInTheDocument(),
    )
  })

  it('follows the step inputs until the sample is edited', () => {
    const step = (inputs: Record<string, unknown>) =>
      node({ params: { code: 'n', inputs }, type: 'script' })
    const { rerender } = render(
      <ScriptPreview node={step({})} orgSlug="acme" />,
    )
    const sample = () =>
      JSON.parse(
        (screen.getByLabelText('Sample inputs') as HTMLTextAreaElement).value,
      )
    rerender(<ScriptPreview node={step({ n: 3 })} orgSlug="acme" />)
    expect(sample()).toEqual({ n: 3 })
    fireEvent.change(screen.getByLabelText('Sample inputs'), {
      target: { value: '{"n": 9}' },
    })
    rerender(<ScriptPreview node={step({ n: 4 })} orgSlug="acme" />)
    expect(sample()).toEqual({ n: 9 })
  })

  it('does not run sample inputs that are not a JSON object', async () => {
    renderPreview()
    fireEvent.change(screen.getByLabelText('Sample inputs'), {
      target: { value: '[1, 2]' },
    })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Run script' })).toBeDisabled(),
    )
    expect(screen.getByText('Write a JSON object.')).toBeInTheDocument()
  })
})
