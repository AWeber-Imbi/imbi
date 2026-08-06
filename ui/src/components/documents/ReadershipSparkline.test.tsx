import { fireEvent } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'
import type { DocumentTrendPoint } from '@/types'

import { ReadershipSparkline } from './ReadershipSparkline'

const TREND: DocumentTrendPoint[] = [
  { day: '2026-05-01', readers: 1, views: 2 },
  { day: '2026-05-02', readers: 0, views: 0 },
  { day: '2026-05-03', readers: 3, views: 7 },
]

describe('ReadershipSparkline', () => {
  it('renders nothing when there is no trend', () => {
    const { container } = render(<ReadershipSparkline trend={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('captions the range covered', () => {
    render(<ReadershipSparkline trend={TREND} />)
    expect(screen.getByText(/May 1, 2026 to May 3, 2026/)).toBeInTheDocument()
  })

  it('pins a hovered day into the caption', () => {
    const { container } = render(<ReadershipSparkline trend={TREND} />)
    const hits = screen
      .getByRole('img', { name: 'Views per day' })
      .querySelectorAll('rect')

    fireEvent.mouseEnter(hits[2])

    expect(container.textContent).toContain('May 3, 2026 · 7 views · 3 readers')
  })

  it('singularizes a one-view day and restores the range on leave', () => {
    const { container } = render(<ReadershipSparkline trend={TREND} />)
    const chart = screen.getByRole('img', { name: 'Views per day' })
    const hits = chart.querySelectorAll('rect')

    fireEvent.mouseEnter(hits[0])
    expect(container.textContent).toContain('2 views · 1 reader')

    fireEvent.mouseLeave(chart)
    expect(container.textContent).toContain('May 1, 2026 to May 3, 2026')
  })

  it('leaves an unparseable day as-is', () => {
    render(
      <ReadershipSparkline
        trend={[{ day: 'not-a-day', readers: 0, views: 0 }]}
      />,
    )
    expect(screen.getByText(/not-a-day/)).toBeInTheDocument()
  })
})
