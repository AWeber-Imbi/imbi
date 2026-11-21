import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { BlueprintFields } from '../ProjectAttributesSection'

describe('BlueprintFields', () => {
  it('lets a later section override a field, as the API does', () => {
    render(
      <BlueprintFields
        patch={vi.fn()}
        pendingPath={null}
        readOnly
        sections={[
          {
            name: 'Base',
            properties: { severity: { title: 'Old', type: 'string' } },
            slug: 'base',
          },
          {
            name: 'Incident',
            properties: { severity: { title: 'Severity', type: 'string' } },
            slug: 'incident',
          },
        ]}
        valueOf={() => 'sev1'}
      />,
    )
    expect(screen.getByText('Severity')).toBeInTheDocument()
    expect(screen.queryByText('Old')).toBeNull()
  })
})
