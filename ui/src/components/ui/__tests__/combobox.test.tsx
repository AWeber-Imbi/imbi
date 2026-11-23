import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'

import { Combobox } from '../combobox'
import { Label } from '../label'

const TEAMS = [
  { label: 'Platform Engineering', value: 'platform' },
  { label: 'Data Services', value: 'data' },
]

describe('Combobox', () => {
  it('is named by a Label that points at its id', () => {
    render(
      <>
        <Label htmlFor="team">Team</Label>
        <Combobox id="team" onChange={vi.fn()} options={TEAMS} value="" />
      </>,
    )
    expect(screen.getByRole('combobox', { name: 'Team' })).toBeInTheDocument()
  })

  it('shows the selected option label', () => {
    render(<Combobox onChange={vi.fn()} options={TEAMS} value="data" />)
    expect(screen.getByRole('combobox')).toHaveTextContent('Data Services')
  })

  it('offers only the options when not creatable', async () => {
    render(<Combobox onChange={vi.fn()} options={TEAMS} value="" />)
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.type(screen.getByPlaceholderText('Search...'), 'ops')
    expect(screen.getByText('No results found.')).toBeInTheDocument()
    expect(screen.queryByText(/Use “ops”/)).not.toBeInTheDocument()
  })

  it('takes a typed value when creatable', async () => {
    const onChange = vi.fn()
    render(<Combobox creatable onChange={onChange} options={TEAMS} value="" />)
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.type(screen.getByPlaceholderText('Search...'), 'ops')
    expect(screen.queryByText('No results found.')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('option', { name: /Use “ops”/ }))
    expect(onChange).toHaveBeenCalledWith('ops')
  })

  it('does not offer a typed value that is an option', async () => {
    render(<Combobox creatable onChange={vi.fn()} options={TEAMS} value="" />)
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.type(screen.getByPlaceholderText('Search...'), 'data')
    expect(screen.queryByText(/Use “data”/)).not.toBeInTheDocument()
  })

  it('shows a value that is not an option when creatable', () => {
    render(
      <Combobox creatable onChange={vi.fn()} options={TEAMS} value="ops" />,
    )
    expect(screen.getByRole('combobox')).toHaveTextContent('ops')
  })
})
