import { describe, expect, it } from 'vitest'

import { resolvePrefixPlaceholders } from '../configPrefix'

describe('resolvePrefixPlaceholders', () => {
  it('fills a placeholder every key agrees on', () => {
    expect(
      resolvePrefixPlaceholders('/cp/${project_type_slug}/control-panel/', [
        '/cp/api/control-panel/testing/host',
        '/cp/api/control-panel/production/host',
      ]),
    ).toBe('/cp/api/control-panel/')
  })

  it('leaves a placeholder that resolves differently per key', () => {
    expect(
      resolvePrefixPlaceholders('/cp/${environment}/control-panel/', [
        '/cp/testing/control-panel/host',
        '/cp/production/control-panel/host',
      ]),
    ).toBe('/cp/${environment}/control-panel/')
  })

  it('resolves each placeholder independently', () => {
    expect(
      resolvePrefixPlaceholders(
        '/cp/${project_type_slug}/${environment}/panel/',
        ['/cp/api/testing/panel/host', '/cp/api/production/panel/host'],
      ),
    ).toBe('/cp/api/${environment}/panel/')
  })

  it('returns the template when no key matches', () => {
    expect(
      resolvePrefixPlaceholders('/cp/${project_type_slug}/panel/', [
        '/other/api/panel/host',
      ]),
    ).toBe('/cp/${project_type_slug}/panel/')
  })

  it('returns the template unchanged without placeholders or keys', () => {
    expect(resolvePrefixPlaceholders('/cp/api/panel/', [])).toBe(
      '/cp/api/panel/',
    )
    expect(resolvePrefixPlaceholders('/cp/${a}/', [])).toBe('/cp/${a}/')
  })
})
