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
  private cachedSets: IconSetDefinition[] | null = null

  register(set: IconSetDefinition): void {
    this.sets.set(set.id, set)
    this.cachedSets = null
  }

  getSets(): IconSetDefinition[] {
    if (!this.cachedSets) {
      this.cachedSets = Array.from(this.sets.values()).sort((a, b) =>
        a.label.localeCompare(b.label),
      )
    }
    return this.cachedSets
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
          icon.value.toLowerCase().includes(q) ||
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
