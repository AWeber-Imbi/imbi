import { describe, expect, it, vi } from 'vitest'

import { updateCurrentUserDisplayName } from '@/api/endpoints'
import { fireEvent, render, screen, waitFor } from '@/test/utils'

import { Settings } from '../../Settings'
import { SettingsAccount } from '../SettingsAccount'

// fallow-ignore-next-line unresolved-import
vi.mock('@/api/endpoints', () => ({
  updateCurrentUserDisplayName: vi.fn().mockResolvedValue(undefined),
}))

// fallow-ignore-next-line unresolved-import
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { display_name: 'Old Name', email: 'ann@example.com' },
  }),
}))

vi.mock('../SettingsApiKeys', () => ({ SettingsApiKeys: () => null }))
vi.mock('../SettingsConnections', () => ({ SettingsConnections: () => null }))
vi.mock('../SettingsSecurity', () => ({ SettingsSecurity: () => null }))

describe('SettingsAccount', () => {
  it('saves the display name through PATCH /users/me', async () => {
    render(<SettingsAccount />)
    fireEvent.click(screen.getByText('Old Name'))
    const input = screen.getByDisplayValue('Old Name')
    fireEvent.change(input, { target: { value: ' Ann ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() =>
      expect(vi.mocked(updateCurrentUserDisplayName).mock.calls[0][0]).toBe(
        'Ann',
      ),
    )
  })

  it('has no controls that save nothing', () => {
    render(<Settings />)
    expect(screen.queryByRole('switch')).toBeNull()
    expect(screen.queryByRole('tab', { name: /Notifications/ })).toBeNull()
    expect(screen.getByRole('tab', { name: /Account/ })).toBeInTheDocument()
  })
})
