import { describe, expect, it } from 'vitest'

import { DELIVERY_MODE_OPTIONS, resolveDelivery } from '../delivery'

const DEPLOYABLE = { deployable: true, releasable: false }
const RELEASABLE = { deployable: false, releasable: true }
const NEITHER = { deployable: false, releasable: false }

describe('resolveDelivery', () => {
  it('passes the project type flags through by default', () => {
    expect(resolveDelivery({ project_types: [DEPLOYABLE] })).toEqual({
      deployable: true,
      releasable: false,
    })
    expect(resolveDelivery({ project_types: [RELEASABLE] })).toEqual({
      deployable: false,
      releasable: true,
    })
    expect(resolveDelivery({ project_types: [NEITHER] })).toEqual({
      deployable: false,
      releasable: false,
    })
    expect(resolveDelivery({})).toEqual({
      deployable: false,
      releasable: false,
    })
  })

  it('keeps both flags for a project carrying both kinds of type', () => {
    expect(
      resolveDelivery({
        delivery_mode: 'project-type',
        project_types: [RELEASABLE, DEPLOYABLE],
      }),
    ).toEqual({ deployable: true, releasable: true })
  })

  it('lets an explicit mode replace the type flags', () => {
    expect(
      resolveDelivery({
        delivery_mode: 'releasable',
        project_types: [DEPLOYABLE],
      }),
    ).toEqual({ deployable: false, releasable: true })
    expect(
      resolveDelivery({
        delivery_mode: 'deployable',
        project_types: [RELEASABLE],
      }),
    ).toEqual({ deployable: true, releasable: false })
  })

  it('clears both flags when disabled, whatever the types say', () => {
    expect(
      resolveDelivery({
        delivery_mode: 'disabled',
        project_types: [DEPLOYABLE, RELEASABLE],
      }),
    ).toEqual({ deployable: false, releasable: false })
  })

  it('treats an unknown mode as by-project-type', () => {
    expect(
      resolveDelivery({
        delivery_mode: 'sometimes',
        project_types: [DEPLOYABLE],
      }),
    ).toEqual({ deployable: true, releasable: false })
  })

  it('offers every mode exactly once, by-project-type first', () => {
    expect(DELIVERY_MODE_OPTIONS.map((o) => o.value)).toEqual([
      'project-type',
      'deployable',
      'releasable',
      'disabled',
    ])
  })
})
