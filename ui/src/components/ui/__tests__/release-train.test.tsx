import { describe, expect, it } from 'vitest'

import { ThemeProvider } from '@/contexts/ThemeContext'
import { render, screen } from '@/test/utils'
import type { Environment } from '@/types'

import { ReleaseTrain } from '../release-train'

function env(slug: string, name: string, sort_order: number): Environment {
  return { label_color: null, name, slug, sort_order } as never
}

const STAGING = env('staging', 'Staging', 1)
const PRODUCTION = env('production', 'Production', 2)

function renderTrain(stops: Parameters<typeof ReleaseTrain>[0]['stops']) {
  render(
    <ThemeProvider>
      <ReleaseTrain stops={stops} />
    </ThemeProvider>,
  )
}

describe('ReleaseTrain', () => {
  it('titles a stop with a value by its value', () => {
    renderTrain([{ environment: STAGING, value: 'a41f9c2' }])
    expect(screen.getByTitle('Staging: a41f9c2')).toBeInTheDocument()
  })

  it('titles a stop marked done without a value as deployed', () => {
    renderTrain([{ done: true, environment: STAGING }])
    expect(screen.getByTitle('Staging · deployed')).toBeInTheDocument()
  })

  it('titles a stop that is not done as not deployed', () => {
    renderTrain([{ environment: PRODUCTION }])
    expect(screen.getByTitle('Production · not deployed')).toBeInTheDocument()
  })

  it('keeps an explicit title', () => {
    renderTrain([{ done: true, environment: STAGING, title: 'Promoted' }])
    expect(screen.getByTitle('Promoted')).toBeInTheDocument()
  })
})
