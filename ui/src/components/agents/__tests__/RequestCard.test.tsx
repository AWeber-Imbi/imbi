import { describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/utils'
import type { Ticket } from '@/types'

import type { TaskRequestView } from '../taskEvents'
import { InputRequiredTab } from '../TaskTabs'
import { task } from './taskFixtures'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

vi.mock('@/hooks/useHasPermission', () => ({
  useHasPermission: () => false,
}))

vi.mock('../agentQueries', () => ({
  useAgentList: () => ({ data: [] }),
}))

function renderCard(status: TaskRequestView['status']) {
  const t = task({ status: 'closed' }) as unknown as Ticket
  return render(
    <InputRequiredTab orgSlug="acme" requests={[request(status)]} task={t} />,
  )
}

function request(status: TaskRequestView['status']): TaskRequestView {
  return {
    answer: null,
    artifact_digests: null,
    artifacts: [],
    expires_at: null,
    id: `r-${status}`,
    kind: 'feedback',
    opened_at: '2026-11-18T10:00:00Z',
    opened_by: null,
    options: [],
    resolved_at: '2026-11-18T11:00:00Z',
    resolved_by: null,
    status,
    title: `Request that was ${status}`,
    why: null,
  }
}

describe('RequestCard outcome', () => {
  it.each([
    ['answered', 'lucide-check'],
    ['rejected', 'lucide-x'],
    ['expired', 'lucide-clock'],
    ['withdrawn', 'lucide-undo2'],
  ] as const)('marks a %s request with its own icon', (status, icon) => {
    const { container } = renderCard(status)
    expect(container.querySelector(`svg.${icon}`)).not.toBeNull()
  })

  it('does not mark a withdrawn request as answered', () => {
    const { container } = renderCard('withdrawn')
    expect(screen.getByText('Withdrawn')).toBeInTheDocument()
    expect(container.querySelector('svg.lucide-check')).toBeNull()
  })
})
