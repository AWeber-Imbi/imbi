import { describe, expect, it } from 'vitest'

import { fireEvent, render, screen } from '@/test/utils'
import type { AgentTask } from '@/types'

import { TaskUsageCard } from '../TaskUsageCards'
import { task } from './taskFixtures'

function renderCard(over: Record<string, unknown> = {}) {
  render(
    <TaskUsageCard events={[]} task={task(over) as unknown as AgentTask} />,
  )
  fireEvent.pointerUp(screen.getByRole('button', { name: /tokens/ }), {
    pointerType: 'touch',
  })
}

describe('TaskUsageCard', () => {
  it('opens on a tap', () => {
    renderCard()
    expect(screen.getByText('Total')).toBeInTheDocument()
  })

  it('gives the budget bar its value', () => {
    renderCard({ budget: '5.000000', cost_total: '1.250000' })
    expect(
      screen.getByRole('progressbar', { name: 'Budget used' }),
    ).toHaveAttribute('aria-valuenow', '25')
  })

  it('names the budget to a screen reader', () => {
    renderCard({ budget: '5.000000', cost_total: '1.250000' })
    expect(
      screen.getByRole('button', { name: /tokens, \$1\.25 of \$5\.00$/ }),
    ).toBeInTheDocument()
  })

  it('treats a zero budget as a budget', () => {
    renderCard({ budget: '0', cost_total: '0.120000' })
    expect(screen.getByText('Over budget')).toHaveClass('text-danger')
    expect(
      screen.getByRole('progressbar', { name: 'Budget used' }),
    ).toHaveAttribute('aria-valuenow', '100')
  })
})
