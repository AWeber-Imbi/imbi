import { describe, expect, it } from 'vitest'

import { deriveArtifact } from './artifact'

describe('deriveArtifact', () => {
  it('returns unknown with no pull command when no package link exists', () => {
    const a = deriveArtifact({ links: {}, name: 'lib' })
    expect(a.kind).toBe('unknown')
    expect(a.pull).toBeNull()
    expect(a.indexUrl).toBeNull()
  })

  it('derives a pip install command for a pypi link', () => {
    const a = deriveArtifact({
      links: { pypi: 'https://pypi.org/project/address-verification/' },
      name: 'address-verification',
    })
    expect(a.kind).toBe('library')
    expect(a.pull).toBe('pip install address-verification')
    expect(a.indexUrl).toBe('https://pypi.org/project/address-verification/')
  })

  it('derives a docker pull command for a ghcr link', () => {
    const a = deriveArtifact({
      links: { ghcr: 'https://ghcr.io/aweber/address-verification' },
      name: 'address-verification',
    })
    expect(a.kind).toBe('container')
    expect(a.pull).toBe('docker pull ghcr.io/aweber/address-verification')
  })
})
