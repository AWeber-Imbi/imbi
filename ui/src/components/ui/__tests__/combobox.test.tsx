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
})
