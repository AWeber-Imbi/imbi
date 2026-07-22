import { beforeAll, describe, expect, it } from 'vitest'

import { iconRegistry } from '@/lib/icon-registry'
import { iconSet as awsSet } from '@/lib/icon-sets/aws'
import { iconSet as deviconSet } from '@/lib/icon-sets/devicon'
import { iconSet as lucideSet } from '@/lib/icon-sets/lucide'
import { iconSet as phosphorSet } from '@/lib/icon-sets/phosphor'
import { iconSet as simpleIconsSet } from '@/lib/icon-sets/simple-icons'
import { iconSet as tablerSet } from '@/lib/icon-sets/tabler'

beforeAll(() => {
  iconRegistry.register(lucideSet)
  iconRegistry.register(simpleIconsSet)
  iconRegistry.register(phosphorSet)
  iconRegistry.register(tablerSet)
  iconRegistry.register(deviconSet)
  iconRegistry.register(awsSet)
})

describe('Lucide icon set', () => {
  it('registers under id "lucide" with label "Lucide"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'lucide')
    expect(set).toBeDefined()
    expect(set?.label).toBe('Lucide')
  })

  it('has icons sorted alphabetically by label', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'lucide')!
    const labels = set.icons.map((i) => i.label)
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b)))
  })

  it('resolves lucide-house', () => {
    expect(iconRegistry.resolve('lucide-house')).not.toBeNull()
  })

  it('resolves lucide-settings', () => {
    expect(iconRegistry.resolve('lucide-settings')).not.toBeNull()
  })

  it('icon values use lucide- prefix', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'lucide')!
    expect(set.icons.every((i) => i.value.startsWith('lucide-'))).toBe(true)
  })

  it('returns null for unrecognised value', () => {
    expect(iconRegistry.resolve('totally-unknown-xyz-999')).toBeNull()
  })
})

describe('Simple Icons icon set', () => {
  it('registers under id "simple-icons" with label "Simple Icons"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'simple-icons')
    expect(set).toBeDefined()
    expect(set?.label).toBe('Simple Icons')
  })

  it('resolves si-github', () => {
    expect(iconRegistry.resolve('si-github')).not.toBeNull()
  })

  it('resolves si-typescript', () => {
    expect(iconRegistry.resolve('si-typescript')).not.toBeNull()
  })

  it('icon values use si- prefix', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'simple-icons')!
    expect(set.icons.every((i) => i.value.startsWith('si-'))).toBe(true)
  })

  it('returns null for lucide- prefixed values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'simple-icons')!
    expect(set.resolve('lucide-home')).toBeNull()
  })
})

describe('Phosphor icon set', () => {
  it('registers under id "phosphor" with label "Phosphor"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'phosphor')
    expect(set).toBeDefined()
    expect(set?.label).toBe('Phosphor')
  })

  it('resolves phosphor-house', () => {
    expect(iconRegistry.resolve('phosphor-house')).not.toBeNull()
  })

  it('resolves phosphor-star', () => {
    expect(iconRegistry.resolve('phosphor-star')).not.toBeNull()
  })

  it('icon values use phosphor- prefix', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'phosphor')!
    expect(set.icons.every((i) => i.value.startsWith('phosphor-'))).toBe(true)
  })

  it('returns null for non-phosphor values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'phosphor')!
    expect(set.resolve('lucide-home')).toBeNull()
  })
})

describe('Tabler icon set', () => {
  it('registers under id "tabler" with label "Tabler"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'tabler')
    expect(set).toBeDefined()
    expect(set?.label).toBe('Tabler')
  })

  it('resolves tabler-home', () => {
    expect(iconRegistry.resolve('tabler-home')).not.toBeNull()
  })

  it('resolves tabler-home-filled', () => {
    expect(iconRegistry.resolve('tabler-home-filled')).not.toBeNull()
  })

  it('resolves tabler-settings', () => {
    expect(iconRegistry.resolve('tabler-settings')).not.toBeNull()
  })

  it('icon values use tabler- prefix', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'tabler')!
    expect(set.icons.every((i) => i.value.startsWith('tabler-'))).toBe(true)
  })

  it('returns null for non-tabler values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'tabler')!
    expect(set.resolve('lucide-home')).toBeNull()
  })
})

describe('Devicon icon set', () => {
  it('registers under id "devicon" with label "Devicon"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'devicon')
    expect(set).toBeDefined()
    expect(set?.label).toBe('Devicon')
  })

  it('icon values use devicon- prefix', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'devicon')!
    expect(set.icons.every((i) => i.value.startsWith('devicon-'))).toBe(true)
  })

  it('returns null for non-devicon values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'devicon')!
    expect(set.resolve('lucide-home')).toBeNull()
  })

  it('returns null for unknown devicon values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'devicon')!
    expect(set.resolve('devicon-nonexistent-xyz-999')).toBeNull()
  })
})

describe('AWS icon set', () => {
  it('registers under id "aws" with label "AWS"', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'aws')
    expect(set).toBeDefined()
    expect(set?.label).toBe('AWS')
  })

  it('returns null for lucide- prefixed values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'aws')!
    expect(set.resolve('lucide-home')).toBeNull()
  })

  it('returns null for devicon- prefixed values', () => {
    const set = iconRegistry.getSets().find((s) => s.id === 'aws')!
    expect(set.resolve('devicon-javascript-original')).toBeNull()
  })
})
