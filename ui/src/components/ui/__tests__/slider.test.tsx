import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/utils'

import { Slider } from '../slider'

describe('Slider', () => {
  it('names the thumb with aria-label', () => {
    render(<Slider aria-label="Max results" defaultValue={[25]} max={100} />)
    expect(
      screen.getByRole('slider', { name: 'Max results' }),
    ).toBeInTheDocument()
  })

  it('names the thumb with aria-labelledby', () => {
    render(
      <>
        <span id="threshold-label">Similarity threshold</span>
        <Slider
          aria-labelledby="threshold-label"
          defaultValue={[0.5]}
          max={1}
        />
      </>,
    )
    expect(
      screen.getByRole('slider', { name: 'Similarity threshold' }),
    ).toBeInTheDocument()
  })

  it('marks a disabled slider', () => {
    render(<Slider aria-label="Locked" defaultValue={[1]} disabled max={2} />)
    expect(screen.getByRole('slider')).toHaveAttribute('data-disabled')
  })
})
