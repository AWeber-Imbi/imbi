import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Advisory } from '@/types'

import { AdvisoryChips } from '../AdvisoryChips'

const advisory = (overrides: Partial<Advisory> = {}): Advisory => ({
  cve_id: 'CVE-2025-0001',
  url: 'https://www.cve.org/CVERecord?id=CVE-2025-0001',
  ...overrides,
})

describe('AdvisoryChips', () => {
  it('shows the catalog severity and puts the description in the tooltip', () => {
    render(
      <AdvisoryChips
        advisories={[
          advisory({
            cvss_score: 9.8,
            description: 'A crafted request runs code.',
            severity: 'CRITICAL',
            title: 'RCE',
          }),
        ]}
      />,
    )
    expect(screen.getByText('Critical 9.8')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute(
      'title',
      'RCE\n\nA crafted request runs code.',
    )
  })

  it('shows no severity badge when the catalog has none', () => {
    render(<AdvisoryChips advisories={[advisory()]} />)
    expect(screen.getByText('CVE-2025-0001')).toBeInTheDocument()
    expect(screen.queryByText(/Critical|High|Medium|Low/)).toBeNull()
  })
})
