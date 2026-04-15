# Icon Picker Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Devicon, Phosphor, and Tabler icon sets to the admin icon picker via an extensible `IconRegistry` pattern, alphabetize set tabs, and default to Lucide.

**Architecture:** A new `IconRegistry` class (singleton `iconRegistry`) lets each icon set self-register on module import. `icons.ts` is slimmed to side-effect imports of all six set files plus delegating `getIcon()`/`getIconUrl()` through the registry. The picker reads `iconRegistry.getSets()` (automatically alphabetical) and defaults to `'lucide'`.

**Tech Stack:** TypeScript strict, React 18, Vite (`import.meta.glob` for URL-based sets), Vitest/jsdom; `devicon` (SVG files), `@phosphor-icons/react`, `@tabler/icons-react`.

---

**Working directory for all commands:** `.worktrees/feature/icon-improvements`

(i.e., `/Volumes/Source/imbi/imbi-ui/.worktrees/feature/icon-improvements`)

---

## File Map

| Action | Path |
|--------|------|
| Create | `src/lib/icon-registry.ts` |
| Create | `src/lib/icon-sets/lucide.ts` |
| Create | `src/lib/icon-sets/simple-icons.ts` |
| Create | `src/lib/icon-sets/aws.ts` |
| Create | `src/lib/icon-sets/devicon.ts` |
| Create | `src/lib/icon-sets/phosphor.ts` |
| Create | `src/lib/icon-sets/tabler.ts` |
| Create | `src/lib/__tests__/icon-registry.test.ts` |
| Create | `src/lib/__tests__/icon-sets.test.ts` |
| Modify | `src/lib/icons.ts` |
| Modify | `src/components/ui/icon-picker.tsx` |
| Modify | `package.json` (via npm install) |

---

## Task 1: Install new icon packages

**Files:** `package.json`, `package-lock.json`

- [ ] **Step 1: Install packages**

```bash
npm install devicon @phosphor-icons/react @tabler/icons-react
```

Expected: packages added under `dependencies`, no errors.

- [ ] **Step 2: Verify installs**

```bash
ls node_modules/devicon/icons/ | head -5
ls node_modules/@phosphor-icons/react/dist/csr/ | head -5
ls node_modules/@tabler/icons-react/dist/esm/icons/ | head -5
```

Expected: directory listings with SVG/JS files visible.

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "Add devicon, @phosphor-icons/react, @tabler/icons-react"
```

---

## Task 2: Create `IconRegistry` with tests

**Files:**
- Create: `src/lib/icon-registry.ts`
- Create: `src/lib/__tests__/icon-registry.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/lib/__tests__/icon-registry.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { IconRegistry } from '@/lib/icon-registry'
import type { IconSetDefinition } from '@/lib/icon-registry'

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
    resolve: (v) => (v.startsWith(`${id}-`) ? (() => null) as never : null),
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
      const mockComponent = (() => null) as never
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
  })

  describe('search()', () => {
    it('returns empty array for empty query', () => {
      registry.register(
        makeSet('aaa', 'Aaa', [{ label: 'Home', value: 'aaa-home' }]),
      )
      expect(registry.search('')).toEqual([])
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
          { label: 'Star', value: 'aaa-star', keywords: ['favorite', 'bookmark'] },
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
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test -- src/lib/__tests__/icon-registry.test.ts
```

Expected: FAIL — "Cannot find module '@/lib/icon-registry'"

- [ ] **Step 3: Create `src/lib/icon-registry.ts`**

```typescript
import type { ComponentType, SVGProps } from 'react'

export type IconComponent = ComponentType<
  SVGProps<SVGSVGElement> & { size?: number | string }
>

export interface IconEntry {
  label: string
  value: string
  keywords?: string[]
}

export interface IconSetDefinition {
  id: string
  label: string
  description: string
  valueFormat: string
  icons: IconEntry[]
  resolve: (value: string) => IconComponent | null
  resolveUrl: (value: string, color?: string) => string | null
}

export interface AgentIconManifest {
  sets: {
    id: string
    label: string
    description: string
    valueFormat: string
    examples: string[]
    count: number
  }[]
}

export class IconRegistry {
  private sets: Map<string, IconSetDefinition> = new Map()

  register(set: IconSetDefinition): void {
    this.sets.set(set.id, set)
  }

  getSets(): IconSetDefinition[] {
    return Array.from(this.sets.values()).sort((a, b) =>
      a.label.localeCompare(b.label),
    )
  }

  resolve(value: string): IconComponent | null {
    for (const set of this.sets.values()) {
      const result = set.resolve(value)
      if (result !== null) return result
    }
    return null
  }

  resolveUrl(value: string, color?: string): string | null {
    for (const set of this.sets.values()) {
      const result = set.resolveUrl(value, color)
      if (result !== null) return result
    }
    return null
  }

  search(query: string, setId?: string): IconEntry[] {
    const sets = setId
      ? ([this.sets.get(setId)].filter(Boolean) as IconSetDefinition[])
      : Array.from(this.sets.values())
    const q = query.toLowerCase().trim()
    if (!q) return []
    const results: IconEntry[] = []
    for (const set of sets) {
      for (const icon of set.icons) {
        if (
          icon.label.toLowerCase().includes(q) ||
          icon.value.includes(q) ||
          icon.keywords?.some((k) => k.toLowerCase().includes(q))
        ) {
          results.push(icon)
        }
      }
    }
    return results
  }

  toAgentManifest(): AgentIconManifest {
    return {
      sets: this.getSets().map((set) => ({
        id: set.id,
        label: set.label,
        description: set.description,
        valueFormat: set.valueFormat,
        examples: set.icons.slice(0, 4).map((i) => i.value),
        count: set.icons.length,
      })),
    }
  }
}

export const iconRegistry = new IconRegistry()
```

- [ ] **Step 4: Run test — verify it passes**

```bash
npm test -- src/lib/__tests__/icon-registry.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/icon-registry.ts src/lib/__tests__/icon-registry.test.ts
git commit -m "Add IconRegistry class with agent manifest support"
```

---

## Task 3: Extract Lucide into `src/lib/icon-sets/lucide.ts`

**Files:**
- Create: `src/lib/icon-sets/lucide.ts`
- Create: `src/lib/__tests__/icon-sets.test.ts`

- [ ] **Step 1: Write failing test**

Create `src/lib/__tests__/icon-sets.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { iconRegistry } from '@/lib/icon-registry'
import '@/lib/icon-sets/lucide'

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

  it('resolves lucide-home', () => {
    expect(iconRegistry.resolve('lucide-home')).not.toBeNull()
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
```

- [ ] **Step 2: Run test — verify it fails**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: FAIL — "Cannot find module '@/lib/icon-sets/lucide'"

- [ ] **Step 3: Create `src/lib/icon-sets/lucide.ts`**

```typescript
import { icons as lucideIcons } from 'lucide-react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

export const LUCIDE_ICONS: IconEntry[] = Object.keys(lucideIcons)
  .filter((k) => k !== 'default' && k !== 'icons' && k !== 'createLucideIcon')
  .map((k) => ({
    label: k,
    value: `lucide-${k.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()}`,
  }))
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('lucide-')) return null
  const name = toPascalCase(value.slice(7)) as keyof typeof lucideIcons
  return (lucideIcons[name] as IconComponent) || null
}

function resolveUrl(value: string, color?: string): string | null {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    const encoded = btoa(unescape(encodeURIComponent(markup)))
    return `data:image/svg+xml;base64,${encoded}`
  } catch {
    return null
  }
}

iconRegistry.register({
  id: 'lucide',
  label: 'Lucide',
  description: 'General purpose outline icons for UI elements',
  valueFormat: 'lucide-{name}',
  icons: LUCIDE_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 4: Run test — verify it passes**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/icon-sets/lucide.ts src/lib/__tests__/icon-sets.test.ts
git commit -m "Extract Lucide icon set into self-registering module"
```

---

## Task 4: Extract Simple Icons into `src/lib/icon-sets/simple-icons.ts`

**Files:**
- Create: `src/lib/icon-sets/simple-icons.ts`
- Modify: `src/lib/__tests__/icon-sets.test.ts` (append tests)

- [ ] **Step 1: Append failing tests to `src/lib/__tests__/icon-sets.test.ts`**

Add after the Lucide describe block:

```typescript
import '@/lib/icon-sets/simple-icons'

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
    // simple-icons set should not claim lucide- values
    const set = iconRegistry.getSets().find((s) => s.id === 'simple-icons')!
    expect(set.resolve('lucide-home')).toBeNull()
  })
})
```

Also add the import at the top of the file alongside the existing imports:
```typescript
import '@/lib/icon-sets/simple-icons'
```

- [ ] **Step 2: Run test — verify new tests fail**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: new Simple Icons tests FAIL.

- [ ] **Step 3: Create `src/lib/icon-sets/simple-icons.ts`**

```typescript
import * as simpleIcons from '@icons-pack/react-simple-icons'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

const siLookup = simpleIcons as Record<string, unknown>

function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

export const SI_ICONS: IconEntry[] = Object.keys(siLookup)
  .filter((k) => k.startsWith('Si') && !k.endsWith('Hex') && k !== 'default')
  .map((k) => {
    const raw = k.slice(2)
    const kebab = raw.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
    return { label: raw, value: `si-${kebab}` }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('si-')) return null
  const name = 'Si' + toPascalCase(value.slice(3))
  return (siLookup[name] as IconComponent) || null
}

function resolveUrl(value: string, color?: string): string | null {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    const encoded = btoa(unescape(encodeURIComponent(markup)))
    return `data:image/svg+xml;base64,${encoded}`
  } catch {
    return null
  }
}

iconRegistry.register({
  id: 'simple-icons',
  label: 'Simple Icons',
  description: 'Brand icons for popular services, frameworks, and tools',
  valueFormat: 'si-{name}',
  icons: SI_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 4: Run test — verify all tests pass**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/icon-sets/simple-icons.ts src/lib/__tests__/icon-sets.test.ts
git commit -m "Extract Simple Icons set into self-registering module"
```

---

## Task 5: Extract AWS into `src/lib/icon-sets/aws.ts`

**Files:**
- Create: `src/lib/icon-sets/aws.ts`

No unit test — the AWS set uses `import.meta.glob` which resolves at Vite build time and isn't exercised in unit tests. Build verification in Task 11 covers it.

- [ ] **Step 1: Create `src/lib/icon-sets/aws.ts`**

```typescript
import { createElement } from 'react'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

const awsArchGlob = import.meta.glob<string>(
  '/node_modules/aws-svg-icons/lib/Architecture-Service-Icons_07302021/*/64/*.svg',
  { eager: true, import: 'default', query: '?url' },
)
const awsResGlob = import.meta.glob<string>(
  '/node_modules/aws-svg-icons/lib/Resource-Icons_07302021/*/Res_48_Light/*.svg',
  { eager: true, import: 'default', query: '?url' },
)

interface AwsEntry {
  url: string
  label: string
}

function buildAwsIndex(): Record<string, AwsEntry> {
  const index: Record<string, AwsEntry> = {}
  for (const [path, url] of Object.entries(awsArchGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Arch_(.+)_64\.svg$/)
    if (!match) continue
    const raw = match[1]
    index[raw.toLowerCase()] = { url, label: raw.replace(/-/g, ' ') }
  }
  for (const [path, url] of Object.entries(awsResGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Res_(.+)_48_Light\.svg$/)
    if (!match) continue
    const raw = match[1]
    const name = raw.replace(/_/g, '-').toLowerCase()
    index[name] = { url, label: raw.replace(/[_-]/g, ' ') }
  }
  return index
}

const awsIndex = buildAwsIndex()
const awsIconNames = new Set(Object.keys(awsIndex))

export const AWS_ICONS: IconEntry[] = Object.entries(awsIndex)
  .map(([key, entry]) => ({ label: entry.label, value: key }))
  .sort((a, b) => a.label.localeCompare(b.label))

function createImgComponent(url: string): IconComponent {
  const ImgIcon: IconComponent = (props) => {
    const { className, width, height, ...rest } = props as Record<string, unknown>
    return createElement('img', {
      src: url,
      alt: '',
      className,
      width: width ?? 16,
      height: height ?? 16,
      ...rest,
    })
  }
  return ImgIcon
}

function resolveAwsUrl(iconName: string): string | null {
  const key = iconName.toLowerCase()
  const direct = awsIndex[key]
  if (direct) return direct.url
  for (const [k, entry] of Object.entries(awsIndex)) {
    if (k.endsWith(key)) return entry.url
  }
  return null
}

function resolve(value: string): IconComponent | null {
  if (!awsIconNames.has(value)) return null
  const url = resolveAwsUrl(value)
  return url ? createImgComponent(url) : null
}

function resolveUrl(value: string): string | null {
  if (!awsIconNames.has(value)) return null
  return resolveAwsUrl(value)
}

iconRegistry.register({
  id: 'aws',
  label: 'AWS',
  description: 'Amazon Web Services architecture and resource icons',
  valueFormat: '{service-name}',
  icons: AWS_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 2: Commit**

```bash
git add src/lib/icon-sets/aws.ts
git commit -m "Extract AWS icon set into self-registering module"
```

---

## Task 6: Add Devicon icon set

**Files:**
- Create: `src/lib/icon-sets/devicon.ts`

No unit test — uses `import.meta.glob`. Covered by build verification in Task 11.

- [ ] **Step 1: Create `src/lib/icon-sets/devicon.ts`**

```typescript
import { createElement } from 'react'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

const deviconGlob = import.meta.glob<string>(
  '/node_modules/devicon/icons/**/*.svg',
  { eager: true, import: 'default', query: '?url' },
)

// Build lookup: "devicon-javascript-original" → url
const deviconIndex: Record<string, string> = {}
for (const [path, url] of Object.entries(deviconGlob)) {
  const filename = path.split('/').pop()!
  const name = filename.replace('.svg', '') // e.g. "javascript-original"
  deviconIndex[`devicon-${name}`] = url
}

export const DEVICON_ICONS: IconEntry[] = Object.entries(deviconIndex)
  .map(([value]) => ({
    label: value.slice(8).replace(/-/g, ' '), // strip "devicon-" → "javascript original"
    value,
  }))
  .sort((a, b) => a.label.localeCompare(b.label))

function createImgComponent(url: string): IconComponent {
  const ImgIcon: IconComponent = (props) => {
    const { className, width, height, ...rest } = props as Record<string, unknown>
    return createElement('img', {
      src: url,
      alt: '',
      className,
      width: width ?? 16,
      height: height ?? 16,
      ...rest,
    })
  }
  return ImgIcon
}

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('devicon-')) return null
  const url = deviconIndex[value]
  return url ? createImgComponent(url) : null
}

function resolveUrl(value: string): string | null {
  if (!value.startsWith('devicon-')) return null
  return deviconIndex[value] ?? null
}

iconRegistry.register({
  id: 'devicon',
  label: 'Devicon',
  description:
    'Technology and programming language icons, multiple style variants',
  valueFormat: 'devicon-{tech}-{variant}',
  icons: DEVICON_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 2: Commit**

```bash
git add src/lib/icon-sets/devicon.ts
git commit -m "Add Devicon icon set (all variants, URL-based)"
```

---

## Task 7: Add Phosphor icon set

**Files:**
- Create: `src/lib/icon-sets/phosphor.ts`
- Modify: `src/lib/__tests__/icon-sets.test.ts` (append tests)

- [ ] **Step 1: Append failing tests to `src/lib/__tests__/icon-sets.test.ts`**

Add at the top of the file alongside existing imports:
```typescript
import '@/lib/icon-sets/phosphor'
```

Add after the Simple Icons describe block:

```typescript
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
```

- [ ] **Step 2: Run test — verify new tests fail**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: Phosphor tests FAIL.

- [ ] **Step 3: Create `src/lib/icon-sets/phosphor.ts`**

```typescript
import * as PhosphorIcons from '@phosphor-icons/react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

const phosphorLookup = PhosphorIcons as Record<string, unknown>

function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

// Filter to icon components only (functions, PascalCase, not the context object)
export const PHOSPHOR_ICONS: IconEntry[] = Object.keys(phosphorLookup)
  .filter(
    (k) =>
      typeof phosphorLookup[k] === 'function' &&
      /^[A-Z]/.test(k) &&
      k !== 'IconContext',
  )
  .map((k) => ({
    label: k,
    value: `phosphor-${k.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()}`,
  }))
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('phosphor-')) return null
  const name = toPascalCase(value.slice(9))
  const Component = phosphorLookup[name]
  return typeof Component === 'function' ? (Component as IconComponent) : null
}

function resolveUrl(value: string, color?: string): string | null {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        weight: 'regular',
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    const encoded = btoa(unescape(encodeURIComponent(markup)))
    return `data:image/svg+xml;base64,${encoded}`
  } catch {
    return null
  }
}

iconRegistry.register({
  id: 'phosphor',
  label: 'Phosphor',
  description:
    'Flexible icon family for interfaces and diagrams (regular weight)',
  valueFormat: 'phosphor-{name}',
  icons: PHOSPHOR_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 4: Run test — verify all tests pass**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/icon-sets/phosphor.ts src/lib/__tests__/icon-sets.test.ts
git commit -m "Add Phosphor icon set (regular weight)"
```

---

## Task 8: Add Tabler icon set

**Files:**
- Create: `src/lib/icon-sets/tabler.ts`
- Modify: `src/lib/__tests__/icon-sets.test.ts` (append tests)

- [ ] **Step 1: Append failing tests to `src/lib/__tests__/icon-sets.test.ts`**

Add at the top of the file alongside existing imports:
```typescript
import '@/lib/icon-sets/tabler'
```

Add after the Phosphor describe block:

```typescript
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
```

- [ ] **Step 2: Run test — verify new tests fail**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: Tabler tests FAIL.

- [ ] **Step 3: Create `src/lib/icon-sets/tabler.ts`**

```typescript
import * as TablerIcons from '@tabler/icons-react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'

const tablerLookup = TablerIcons as Record<string, unknown>

function toPascalCase(str: string): string {
  return str
    .split('-')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('')
}

// All Tabler icon exports start with "Icon"
export const TABLER_ICONS: IconEntry[] = Object.keys(tablerLookup)
  .filter((k) => typeof tablerLookup[k] === 'function' && k.startsWith('Icon'))
  .map((k) => {
    const stripped = k.slice(4) // "IconHome" → "Home", "IconHomeFilled" → "HomeFilled"
    const kebab = stripped.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
    return { label: stripped, value: `tabler-${kebab}` }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('tabler-')) return null
  const name = 'Icon' + toPascalCase(value.slice(7))
  const Component = tablerLookup[name]
  return typeof Component === 'function' ? (Component as IconComponent) : null
}

function resolveUrl(value: string, color?: string): string | null {
  const Component = resolve(value)
  if (!Component) return null
  try {
    const markup = renderToStaticMarkup(
      createElement(Component, {
        width: 128,
        height: 128,
        ...(color ? { color } : {}),
      }),
    )
    const encoded = btoa(unescape(encodeURIComponent(markup)))
    return `data:image/svg+xml;base64,${encoded}`
  } catch {
    return null
  }
}

iconRegistry.register({
  id: 'tabler',
  label: 'Tabler',
  description: 'Clean open source SVG icons (outline and filled variants)',
  valueFormat: 'tabler-{name}',
  icons: TABLER_ICONS,
  resolve,
  resolveUrl,
})
```

- [ ] **Step 4: Run test — verify all tests pass**

```bash
npm test -- src/lib/__tests__/icon-sets.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/icon-sets/tabler.ts src/lib/__tests__/icon-sets.test.ts
git commit -m "Add Tabler icon set (all variants)"
```

---

## Task 9: Slim down `src/lib/icons.ts`

**Files:**
- Modify: `src/lib/icons.ts` (full replacement)

- [ ] **Step 1: Replace `src/lib/icons.ts` with the following**

```typescript
import { ExternalLink } from 'lucide-react'
import { createElement } from 'react'
import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent } from '@/lib/icon-registry'

// Side-effect imports — each file self-registers with iconRegistry
import '@/lib/icon-sets/lucide'
import '@/lib/icon-sets/simple-icons'
import '@/lib/icon-sets/aws'
import '@/lib/icon-sets/devicon'
import '@/lib/icon-sets/phosphor'
import '@/lib/icon-sets/tabler'

// Re-exports for consumers
export { iconRegistry } from '@/lib/icon-registry'
export type { IconComponent } from '@/lib/icon-registry'
export { AWS_ICONS } from '@/lib/icon-sets/aws'

// ---------------------------------------------------------------------------
// URL cache
// ---------------------------------------------------------------------------
const iconUrlCache = new Map<string, string | null>()

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function createImgComponent(url: string): IconComponent {
  const ImgIcon: IconComponent = (props) => {
    const { className, width, height, ...rest } = props as Record<string, unknown>
    return createElement('img', {
      src: url,
      alt: '',
      className,
      width: width ?? 16,
      height: height ?? 16,
      ...rest,
    })
  }
  return ImgIcon
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Resolve an icon name to a React component.
 *
 * Dispatches through the registry. Falls back to attempting a bare Lucide
 * name (no prefix) for backwards compatibility with legacy stored values.
 */
export function getIcon(
  iconName: string | null | undefined,
  fallback: null,
): IconComponent | null
export function getIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent,
): IconComponent
export function getIcon(
  iconName: string | null | undefined,
  fallback?: IconComponent | null,
): IconComponent | null {
  const fb =
    fallback === undefined ? (ExternalLink as IconComponent) : fallback

  if (!iconName) return fb

  // Uploaded files or absolute URLs → render as <img>
  if (
    iconName.startsWith('/uploads/') ||
    iconName.startsWith('http://') ||
    iconName.startsWith('https://')
  ) {
    return createImgComponent(iconName)
  }

  // Try registry (handles lucide-, si-, aws, devicon-, phosphor-, tabler-)
  const resolved = iconRegistry.resolve(iconName)
  if (resolved) return resolved

  // Backward compat: bare Lucide name stored without prefix (e.g. "external-link")
  const withPrefix = iconRegistry.resolve(`lucide-${iconName}`)
  if (withPrefix) return withPrefix

  return fb
}

/**
 * Resolve an icon name to a URL for use in reagraph GraphNode.icon.
 */
export function getIconUrl(
  iconName: string | null | undefined,
  color?: string,
): string | null {
  if (!iconName) return null
  const cacheKey = color ? `${iconName}@${color}` : iconName
  const cached = iconUrlCache.get(cacheKey)
  if (cached !== undefined) return cached
  const result = computeIconUrl(iconName, color)
  iconUrlCache.set(cacheKey, result)
  return result
}

function computeIconUrl(iconName: string, color?: string): string | null {
  if (iconName.startsWith('/uploads/')) {
    const baseUrl = import.meta.env.VITE_API_URL || '/api'
    return `${baseUrl}${iconName}`
  }
  if (iconName.startsWith('http://') || iconName.startsWith('https://')) {
    return iconName
  }
  return iconRegistry.resolveUrl(iconName, color)
}
```

- [ ] **Step 2: Run full test suite**

```bash
npm test
```

Expected: all existing tests pass (no new failures).

- [ ] **Step 3: Commit**

```bash
git add src/lib/icons.ts
git commit -m "Slim icons.ts to delegate through IconRegistry"
```

---

## Task 10: Update `src/components/ui/icon-picker.tsx`

**Files:**
- Modify: `src/components/ui/icon-picker.tsx` (full replacement)

- [ ] **Step 1: Replace `src/components/ui/icon-picker.tsx` with the following**

```typescript
import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getIcon, iconRegistry } from '@/lib/icons'
import type { IconComponent } from '@/lib/icons'

const MAX_RESULTS = 60

interface IconPickerProps {
  value?: string
  onChange: (value: string) => void
  isDarkMode: boolean
}

export function IconPicker({ value, onChange, isDarkMode }: IconPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [iconSet, setIconSet] = useState('lucide')
  const containerRef = useRef<HTMLDivElement>(null)

  const sets = iconRegistry.getSets()
  const currentSet = sets.find((s) => s.id === iconSet)
  const icons = currentSet?.icons ?? []

  const filtered = useMemo(() => {
    if (!query.trim()) return icons.slice(0, MAX_RESULTS)
    const q = query.toLowerCase()
    const qNoSpace = q.replace(/\s+/g, '')
    const qHyphen = q.replace(/\s+/g, '-')
    return icons
      .filter(
        (i) =>
          i.label.toLowerCase().includes(q) ||
          i.label.toLowerCase().includes(qNoSpace) ||
          i.value.includes(q) ||
          i.value.includes(qHyphen),
      )
      .slice(0, MAX_RESULTS)
  }, [query, icons])

  const handleSelect = useCallback(
    (iconValue: string) => {
      onChange(iconValue)
      setOpen(false)
      setQuery('')
    },
    [onChange],
  )

  const handleClear = useCallback(() => {
    onChange('')
  }, [onChange])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const SelectedIcon: IconComponent | null = value ? getIcon(value) : null

  return (
    <div ref={containerRef} className="relative">
      {/* Current value display */}
      {value ? (
        <div
          className={`flex items-center gap-3 rounded-lg border p-2.5 ${
            isDarkMode
              ? 'border-gray-600 bg-gray-700'
              : 'border-gray-300 bg-white'
          }`}
        >
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className={`flex flex-1 items-center gap-3 text-left text-sm ${
              isDarkMode ? 'text-gray-200' : 'text-gray-900'
            }`}
          >
            {SelectedIcon && <SelectedIcon className="h-5 w-5 flex-shrink-0" />}
            <code
              className={`rounded px-1.5 py-0.5 text-xs ${
                isDarkMode ? 'bg-gray-600' : 'bg-gray-100'
              }`}
            >
              {value}
            </code>
          </button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleClear}
            aria-label="Remove icon"
            className={`h-7 w-7 p-0 ${
              isDarkMode
                ? 'text-gray-400 hover:text-red-400'
                : 'text-gray-500 hover:text-red-600'
            }`}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
            isDarkMode
              ? 'border-gray-600 bg-gray-700 text-gray-400 hover:border-gray-500'
              : 'border-gray-300 bg-white text-gray-500 hover:border-gray-400'
          }`}
        >
          <Search className="h-4 w-4" />
          Pick an icon...
        </button>
      )}

      {/* Dropdown */}
      {open && (
        <div
          className={`absolute z-50 mt-1 w-full rounded-lg border shadow-lg ${
            isDarkMode
              ? 'border-gray-600 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div className="p-2">
            <div className="mb-2 flex flex-wrap gap-1">
              {sets.map((set) => (
                <button
                  key={set.id}
                  type="button"
                  onClick={() => {
                    setIconSet(set.id)
                    setQuery('')
                  }}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    iconSet === set.id
                      ? isDarkMode
                        ? 'bg-blue-600/30 text-blue-300'
                        : 'bg-blue-50 text-blue-700'
                      : isDarkMode
                        ? 'text-gray-400 hover:text-gray-200'
                        : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {set.label}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search
                className={`absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search icons..."
                autoFocus
                className={`pl-9 ${
                  isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                }`}
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto px-2 pb-2">
            {filtered.length === 0 ? (
              <div
                className={`py-6 text-center text-sm ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`}
              >
                No icons found
              </div>
            ) : (
              <div className="grid grid-cols-6 gap-1">
                {filtered.map((icon) => {
                  const Icon = getIcon(icon.value)
                  const isSelected = value === icon.value
                  return (
                    <button
                      key={icon.value}
                      type="button"
                      title={icon.value}
                      onClick={() => handleSelect(icon.value)}
                      className={`flex h-10 w-full items-center justify-center rounded-md transition-colors ${
                        isSelected
                          ? isDarkMode
                            ? 'bg-blue-600/30 ring-1 ring-blue-500'
                            : 'bg-blue-50 ring-1 ring-blue-400'
                          : isDarkMode
                            ? 'hover:bg-gray-700'
                            : 'hover:bg-gray-100'
                      }`}
                    >
                      <Icon
                        className={`h-5 w-5 ${
                          isDarkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}
                      />
                    </button>
                  )
                })}
              </div>
            )}
            {filtered.length === MAX_RESULTS && (
              <p
                className={`mt-2 text-center text-xs ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-400'
                }`}
              >
                Type to narrow results
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run full test suite**

```bash
npm test
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/components/ui/icon-picker.tsx
git commit -m "Update icon picker: registry-driven tabs, default Lucide, alphabetical sets"
```

---

## Task 11: Build verification

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

```bash
npm test
```

Expected: all tests pass with no failures.

- [ ] **Step 2: Run TypeScript build**

```bash
npm run build
```

Expected: build succeeds. The chunk size warning for `index.js` is expected (pre-existing) — do not treat it as a failure.

- [ ] **Step 3: If build fails with TypeScript errors, fix them**

Common issues to check:
- Type mismatch on `IconComponent` — ensure `src/lib/icon-registry.ts` exports `IconComponent` and all icon-set files import it from `@/lib/icon-registry`.
- Unused import warnings from the old `icons.ts` — all original top-level imports (`simpleIcons`, `lucideIcons`, `awsArchGlob`, etc.) should be gone after the replacement in Task 9.

- [ ] **Step 4: Commit any build fixes**

```bash
git add -p   # stage only changed files
git commit -m "Fix TypeScript errors from icon registry refactor"
```

---

## Self-Review Checklist (executor: verify before closing)

- [ ] `iconRegistry.getSets()` returns 6 sets in alphabetical order: AWS, Devicon, Lucide, Phosphor, Simple Icons, Tabler
- [ ] Default picker tab is Lucide (not Simple Icons)
- [ ] `getIcon('si-github')` still returns a component (backward compat)
- [ ] `getIcon('aws-lambda')` still returns a component (backward compat)
- [ ] `getIcon('external-link')` returns ExternalLink (bare Lucide backward compat)
- [ ] `getIconUrl` still works for graph canvas nodes
- [ ] `AWS_ICONS` is still importable from `@/lib/icons` (re-exported)
- [ ] Build passes with no new TypeScript errors
