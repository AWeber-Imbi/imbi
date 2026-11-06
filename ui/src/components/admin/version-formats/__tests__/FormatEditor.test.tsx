import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

import { FormatEditor } from '../FormatEditor'

describe('FormatEditor', () => {
  it('derives the pattern from a calendar scheme', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<FormatEditor onCancel={vi.fn()} onSave={onSave} title="Add" />)

    await user.type(screen.getByPlaceholderText('e.g. Build number'), 'Ubuntu')
    await user.type(screen.getByLabelText('Calendar scheme'), 'YY.0M.MICRO')
    await user.type(screen.getByPlaceholderText('Test a version'), '26.04.1')

    const pattern = screen.getByLabelText('Pattern')
    expect(pattern).toBeDisabled()
    expect(pattern).toHaveValue(
      '^(?P<t0>0|[1-9]\\d{0,2})\\.(?P<t1>1[0-2]|0[1-9])\\.(?P<t2>0|[1-9]\\d*)$',
    )
    expect(screen.getByText('Match')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save format' }))
    expect(onSave).toHaveBeenCalledWith(
      'Ubuntu',
      (pattern as HTMLInputElement).value,
      '26.04.1',
      'YY.0M.MICRO',
    )
  })

  it('explains an invalid scheme and blocks saving', async () => {
    const user = userEvent.setup()
    render(<FormatEditor onCancel={vi.fn()} onSave={vi.fn()} title="Add" />)

    await user.type(screen.getByPlaceholderText('e.g. Build number'), 'Bad')
    await user.type(screen.getByLabelText('Calendar scheme'), 'YYYY.0W.D')

    expect(
      screen.getByText('Weeks cannot be combined with months or days'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save format' })).toBeDisabled()
  })

  it('saves a regular expression with no scheme', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<FormatEditor onCancel={vi.fn()} onSave={onSave} title="Add" />)

    await user.type(screen.getByPlaceholderText('e.g. Build number'), 'Build')
    await user.type(screen.getByLabelText('Pattern'), 'build-\\d+')
    await user.click(screen.getByRole('button', { name: 'Save format' }))

    expect(onSave).toHaveBeenCalledWith('Build', 'build-\\d+', '', null)
  })
})
