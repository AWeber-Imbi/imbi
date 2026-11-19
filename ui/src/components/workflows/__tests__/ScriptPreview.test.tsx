import { beforeEach, describe, expect, it, vi } from 'vitest'

import { previewScript } from '@/api/endpoints'
import { fireEvent, JSON_SOURCE, render, screen, waitFor } from '@/test/utils'

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

  it('hides a result when the step changes during the run', async () => {
    let finish = (_: unknown) => {}
    vi.mocked(previewScript).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    const step = (code: string) =>
      node({ params: { code, inputs: {} }, type: 'script' })
    const { rerender } = render(
      <ScriptPreview node={step('1')} orgSlug="acme" />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Run script' }))
    rerender(<ScriptPreview node={step('2')} orgSlug="acme" />)
    finish({ output: { branch: 'old', result: 1 } })
    await screen.findByRole('button', { name: 'Run script' })
    expect(
      screen.getByText(/The step changed after you ran it/),
    ).toBeInTheDocument()
    expect(screen.queryByText('old')).not.toBeInTheDocument()
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

  it.skipIf(!JSON_SOURCE)(
    'keeps a large integer in the sample as text',
    async () => {
      vi.mocked(previewScript).mockResolvedValue({ output: {}, port: 1 })
      renderPreview()
      fireEvent.change(screen.getByLabelText('Sample inputs'), {
        target: { value: '{"n": 12345678901234567890, "limit": 2}' },
      })
      expect(screen.getByText(/sent as text/)).toBeVisible()
      fireEvent.click(screen.getByRole('button', { name: 'Run script' }))
      await waitFor(() =>
        expect(previewScript).toHaveBeenCalledWith(
          'acme',
          expect.objectContaining({
            inputs: { limit: 2, n: '12345678901234567890' },
          }),
        ),
      )
    },
  )

  it.skipIf(!JSON_SOURCE)(
    'shows no text notice for a sample that is not an object',
    () => {
      renderPreview()
      fireEvent.change(screen.getByLabelText('Sample inputs'), {
        target: { value: '[9007199254740993]' },
      })
      expect(screen.queryByText(/sent as text/)).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Run script' })).toBeDisabled()
    },
  )

  it('does not run sample inputs that are not a JSON object', async () => {
    renderPreview()
    fireEvent.change(screen.getByLabelText('Sample inputs'), {
      target: { value: '[1, 2]' },
    })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Run script' })).toBeDisabled(),
    )
    const sample = screen.getByLabelText('Sample inputs')
    expect(sample).toHaveAttribute('aria-invalid', 'true')
    expect(sample).toHaveAccessibleDescription('Write a JSON object.')
  })
})
