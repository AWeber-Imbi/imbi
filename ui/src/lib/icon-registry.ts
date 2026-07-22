import type { ComponentType, SVGProps } from 'react'

export interface AgentIconManifest {
  sets: {
    count: number
    description: string
    examples: string[]
    id: string
    label: string
    valueFormat: string
  }[]
}

export type IconComponent = ComponentType<
  SVGProps<SVGSVGElement> & { size?: number | string }
>

export interface IconEntry {
  keywords?: string[]
  label: string
  value: string
}

export interface IconSetDefinition {
  description: string
  icons: IconEntry[]
  id: string
  label: string
  resolve: (value: string) => IconComponent | null
  resolveUrl: (value: string, color?: string) => null | string
  valueFormat: string
}

export interface IconSetLoader {
  load: () => Promise<IconSetDefinition>
  // Does this loader own `value`? Evaluated in insertion order; first match wins.
  matches: (value: string) => boolean
  meta: IconSetMeta
}

export interface IconSetMeta {
  description: string
  id: string
  label: string
  valueFormat: string
}

type Listener = () => void

export class IconRegistry {
  private cachedMetas: IconSetMeta[] | null = null
  private cachedSets: IconSetDefinition[] | null = null
  private listeners: Set<Listener> = new Set()
  private loaders: Map<string, IconSetLoader> = new Map()
  private loadPromises: Map<string, Promise<IconSetDefinition>> = new Map()
  private sets: Map<string, IconSetDefinition> = new Map()
  private version = 0

  getLoadedSet(id: string): IconSetDefinition | null {
    return this.sets.get(id) ?? null
  }

  getSetMetas(): IconSetMeta[] {
    if (!this.cachedMetas) {
      const metas: IconSetMeta[] = []
      const seen = new Set<string>()
      for (const loader of this.loaders.values()) {
        metas.push(loader.meta)
        seen.add(loader.meta.id)
      }
      // Include directly-registered sets without a loader (e.g. test fixtures).
      for (const set of this.sets.values()) {
        if (seen.has(set.id)) continue
        metas.push({
          description: set.description,
          id: set.id,
          label: set.label,
          valueFormat: set.valueFormat,
        })
      }
      this.cachedMetas = metas.sort((a, b) => a.label.localeCompare(b.label))
    }
    return this.cachedMetas
  }

  getSets(): IconSetDefinition[] {
    if (!this.cachedSets) {
      this.cachedSets = Array.from(this.sets.values()).sort((a, b) =>
        a.label.localeCompare(b.label),
      )
    }
    return this.cachedSets
  }

  getVersion(): number {
    return this.version
  }

  isLoaded(id: string): boolean {
    return this.sets.has(id)
  }

  loadSet(id: string): Promise<IconSetDefinition | null> {
    const existing = this.sets.get(id)
    if (existing) return Promise.resolve(existing)
    const pending = this.loadPromises.get(id)
    if (pending) return pending
    const loader = this.loaders.get(id)
    if (!loader) return Promise.resolve(null)
    const promise = loader
      .load()
      .then((set) => {
        this.register(set)
        this.loadPromises.delete(id)
        return set
      })
      .catch((err) => {
        this.loadPromises.delete(id)
        throw err
      })
    this.loadPromises.set(id, promise)
    return promise
  }

  loadSetFor(value: string): Promise<IconSetDefinition | null> {
    for (const loader of this.loaders.values()) {
      if (loader.matches(value)) return this.loadSet(loader.meta.id)
    }
    return Promise.resolve(null)
  }

  register(set: IconSetDefinition): void {
    this.sets.set(set.id, set)
    this.cachedSets = null
    this.cachedMetas = null
    this.emit()
  }

  registerLoader(loader: IconSetLoader): void {
    this.loaders.set(loader.meta.id, loader)
    this.cachedMetas = null
    this.emit()
  }

  resolve(value: string): IconComponent | null {
    for (const set of this.sets.values()) {
      const result = set.resolve(value)
      if (result !== null) return result
    }
    return null
  }

  resolveUrl(value: string, color?: string): null | string {
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
          icon.value.toLowerCase().includes(q) ||
          icon.keywords?.some((k) => k.toLowerCase().includes(q))
        ) {
          results.push(icon)
        }
      }
    }
    return results
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  toAgentManifest(): AgentIconManifest {
    return {
      sets: this.getSets().map((set) => ({
        count: set.icons.length,
        description: set.description,
        examples: set.icons.slice(0, 4).map((i) => i.value),
        id: set.id,
        label: set.label,
        valueFormat: set.valueFormat,
      })),
    }
  }

  private emit(): void {
    this.version++
    for (const l of this.listeners) l()
  }
}

export const iconRegistry = new IconRegistry()
