import { describe, it, expect, beforeEach } from 'vitest'
import type { FC } from 'react'
import { IconRegistry } from '@/lib/icon-registry'
import type { IconSetDefinition, IconComponent } from '@/lib/icon-registry'

function makeSet(
  id: string,
  label: string,
  icons: { label: string; value: string }[] = [],
): IconSetDefinition {
  return {
    id,
    label,
    description: `${label} icons`,
    valueFormat: `${id}-{name}`,
    icons,
    resolve: (v) =>
      v.startsWith(`${id}-`) ? ((() => null) as FC as IconComponent) : null,
    resolveUrl: (v) =>
      v.startsWith(`${id}-`) ? `https://example.com/${v}` : null,
  }
}

describe('IconRegistry', () => {
  let registry: IconRegistry

  beforeEach(() => {
    registry = new IconRegistry()
  })

  describe('getSets()', () => {
    it('returns empty array when nothing is registered', () => {
      expect(registry.getSets()).toEqual([])
    })

    it('returns sets sorted alphabetically by label', () => {
      registry.register(makeSet('zzz', 'Zzz'))
      registry.register(makeSet('aaa', 'Aaa'))
      registry.register(makeSet('mmm', 'Mmm'))
      expect(registry.getSets().map((s) => s.id)).toEqual(['aaa', 'mmm', 'zzz'])
    })
  })

  describe('resolve()', () => {
    it('dispatches to the matching set', () => {
      const mockComponent = (() => null) as FC as IconComponent
      const set = makeSet('foo', 'Foo')
      set.resolve = (v) => (v === 'foo-bar' ? mockComponent : null)
      registry.register(set)
      expect(registry.resolve('foo-bar')).toBe(mockComponent)
    })

    it('returns null when no set matches', () => {
      registry.register(makeSet('foo', 'Foo'))
      expect(registry.resolve('unknown-totally-fake-icon')).toBeNull()
    })

    it('returns null when registry is empty', () => {
      expect(registry.resolve('foo-bar')).toBeNull()
    })
  })

  describe('resolveUrl()', () => {
    it('returns url from matching set', () => {
      const set = makeSet('foo', 'Foo')
      set.resolveUrl = (v) =>
        v === 'foo-bar' ? 'https://example.com/foo-bar' : null
      registry.register(set)
      expect(registry.resolveUrl('foo-bar')).toBe('https://example.com/foo-bar')
    })

    it('returns null when no set matches', () => {
      registry.register(makeSet('foo', 'Foo'))
      expect(registry.resolveUrl('unknown-icon')).toBeNull()
    })

    it('returns null when registry is empty', () => {
      expect(registry.resolveUrl('foo-bar')).toBeNull()
    })
  })

  describe('search()', () => {
    it('returns empty array for empty query', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [{ label: 'Home', value: 'aaa-home' }]),
      )
      expect(registry.search('')).toEqual([])
    })

    it('returns empty array for whitespace-only query', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [{ label: 'Home', value: 'aaa-home' }]),
      )
      expect(registry.search('   ')).toEqual([])
    })

    it('finds icons matching the query across all sets', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [
          { label: 'Home', value: 'aaa-home' },
          { label: 'Settings', value: 'aaa-settings' },
        ]),
      )
      registry.register(
        makeSet('bbb', 'Bbb', [{ label: 'Homepage', value: 'bbb-homepage' }]),
      )
      const results = registry.search('home')
      const values = results.map((r) => r.value)
      expect(values).toContain('aaa-home')
      expect(values).toContain('bbb-homepage')
      expect(values).not.toContain('aaa-settings')
    })

    it('filters to a specific set when setId is provided', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [{ label: 'Home', value: 'aaa-home' }]),
      )
      registry.register(
        makeSet('bbb', 'Bbb', [{ label: 'Home', value: 'bbb-home' }]),
      )
      const results = registry.search('home', 'aaa')
      const values = results.map((r) => r.value)
      expect(values).toContain('aaa-home')
      expect(values).not.toContain('bbb-home')
    })

    it('searches keywords when provided', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [
          {
            label: 'Star',
            value: 'aaa-star',
            keywords: ['favorite', 'bookmark'],
          },
        ]),
      )
      const results = registry.search('favorite')
      expect(results.map((r) => r.value)).toContain('aaa-star')
    })
  })

  describe('toAgentManifest()', () => {
    it('returns sets in alphabetical order with metadata', () => {
      registry.register(
        makeSet('zzz', 'Zzz', [{ label: 'Icon1', value: 'zzz-icon1' }]),
      )
      registry.register(
        makeSet('aaa', 'Aaa', [
          { label: 'A', value: 'aaa-a' },
          { label: 'B', value: 'aaa-b' },
          { label: 'C', value: 'aaa-c' },
          { label: 'D', value: 'aaa-d' },
          { label: 'E', value: 'aaa-e' },
        ]),
      )
      const manifest = registry.toAgentManifest()
      expect(manifest.sets[0].id).toBe('aaa')
      expect(manifest.sets[0].count).toBe(5)
      expect(manifest.sets[0].examples).toHaveLength(4)
      expect(manifest.sets[0].examples[0]).toBe('aaa-a')
      expect(manifest.sets[1].id).toBe('zzz')
      expect(manifest.sets[1].count).toBe(1)
    })

    it('includes description and valueFormat', () => {
      registry.register(makeSet('foo', 'Foo'))
      const manifest = registry.toAgentManifest()
      expect(manifest.sets[0].description).toBe('Foo icons')
      expect(manifest.sets[0].valueFormat).toBe('foo-{name}')
    })
  })
})
