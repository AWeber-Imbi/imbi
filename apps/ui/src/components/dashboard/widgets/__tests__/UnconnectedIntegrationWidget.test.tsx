import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { PluginPackage } from '@/types'

import { UnconnectedIntegrationWidget } from '../UnconnectedIntegrationWidget'

// fallow-ignore-next-line unresolved-import
vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}))

const plugin = {
  capabilities: [],
  description: 'desc',
  enabled: true,
  name: 'GitHub',
  slug: 'github',
} as unknown as PluginPackage

describe('UnconnectedIntegrationWidget', () => {
  it('renders a dismiss control and invokes onDismiss when clicked', () => {
    const onDismiss = vi.fn()
    render(
      <UnconnectedIntegrationWidget
        onConnect={vi.fn()}
        onDismiss={onDismiss}
        onManage={vi.fn()}
        pending={false}
        plugin={plugin}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Dismiss GitHub connection prompt',
      }),
    )
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('omits the dismiss control when onDismiss is not provided', () => {
    render(
      <UnconnectedIntegrationWidget
        onConnect={vi.fn()}
        onManage={vi.fn()}
        pending={false}
        plugin={plugin}
      />,
    )

    expect(
      screen.queryByRole('button', {
        name: 'Dismiss GitHub connection prompt',
      }),
    ).not.toBeInTheDocument()
  })
})
