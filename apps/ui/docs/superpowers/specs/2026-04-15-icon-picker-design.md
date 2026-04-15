# Icon Picker Improvements — Design Spec

**Date:** 2026-04-15
**Branch:** feature/icon-improvements

## Overview

Extend the icon picker in the admin UI to support three new icon sets (Devicon, Phosphor, Tabler), alphabetize icon set tabs, default to Lucide, and introduce a registry pattern that provides a clean interface for a future agent-based icon suggestion feature.

## Goals

1. Add Devicon (all variants), Phosphor Icons (regular weight only), and Tabler Icons (all variants)
2. Alphabetize icon set tabs in the picker UI
3. Default selected icon set to Lucide
4. Refactor icon resolution into a registry with a stable, agent-readable interface
5. Design the registry manifest so a future LLM agent can suggest icons given entity context

## Non-Goals

- Implementing the agent suggestion feature (future work)
- Deferred/lazy loading of icon bundles (future optimization)
- Changes to how icons are stored in the database (values remain prefixed strings)

---

## Architecture

### Registry (`src/lib/icon-registry.ts`)

Central registry for all icon sets. Provides a standard interface for the picker, the resolver, and the future agent bridge.

```typescript
interface IconEntry {
  label: string     // display name, e.g. "GitHub"
  value: string     // stored value, e.g. "si-github"
  keywords?: string[] // extra search terms, primarily for agent use
}

interface IconSetDefinition {
  id: string           // e.g. "lucide"
  label: string        // e.g. "Lucide"
  description: string  // human + agent readable, e.g. "General purpose outline icons for UI elements"
  valueFormat: string  // e.g. "lucide-{name}" — for agent manifest
  icons: IconEntry[]
  resolve: (value: string) => IconComponent | null
  resolveUrl: (value: string, color?: string) => string | null
}

interface AgentIconManifest {
  sets: {
    id: string
    label: string
    description: string
    valueFormat: string
    examples: string[]  // 3–5 representative values
    count: number
  }[]
}

class IconRegistry {
  register(set: IconSetDefinition): void
  getSets(): IconSetDefinition[]          // sorted alphabetically by label
  resolve(value: string): IconComponent | null
  resolveUrl(value: string, color?: string): string | null
  search(query: string, setId?: string): IconEntry[]
  toAgentManifest(): AgentIconManifest
}

export const iconRegistry: IconRegistry  // singleton
```

`getSets()` always returns sets in alphabetical label order. The picker reads from this — no hardcoded set list in the component.

### File Structure

Current `src/lib/icons.ts` is split into focused modules:

```text
src/lib/
  icon-registry.ts        ← registry class, interfaces, singleton export
  icon-sets/
    lucide.ts             ← extracted: LUCIDE_ICONS, resolve logic, registers self
    simple-icons.ts       ← extracted: SI_ICONS, resolve logic, registers self
    aws.ts                ← extracted: AWS_ICONS, glob import, registers self
    devicon.ts            ← new: DEVICON_ICONS, glob import, registers self
    phosphor.ts           ← new: PHOSPHOR_ICONS, React components, registers self
    tabler.ts             ← new: TABLER_ICONS, React components, registers self
  icons.ts                ← slim: imports all icon-sets (triggering registration),
                               re-exports getIcon() and getIconUrl() via registry
```

Each icon set file calls `iconRegistry.register(...)` at module load time. `icons.ts` imports all six sets to ensure registration, then delegates `getIcon` and `getIconUrl` to the registry.

The registry's `resolve(value)` dispatches to each set's `resolve` function by trying each registered set in turn. Each set's resolver receives the full prefixed value (e.g. `"lucide-home"`) and is responsible for recognising and stripping its own prefix. A set returns `null` if the value doesn't belong to it.

### Rendering Strategy

| Set | Package | Rendering | Dark mode |
|-----|---------|-----------|-----------|
| Lucide | `lucide-react` | React component | ✓ via `currentColor` |
| Simple Icons | `@icons-pack/react-simple-icons` | React component | brand colors baked in |
| AWS | `aws-svg-icons` | `<img>` via glob URL | — |
| Devicon | `devicon` | `<img>` via glob URL | — |
| Phosphor | `@phosphor-icons/react` | React component, `weight="regular"` | ✓ via `currentColor` |
| Tabler | `@tabler/icons-react` | React component | ✓ via `currentColor` |

Devicon uses `import.meta.glob` with `{ eager: true, query: '?url' }` — SVG files are emitted as separate assets (not inlined into JS). Phosphor and Tabler are bundled as React components and will increase the JS bundle; this is accepted as a known trade-off to be addressed in a future optimization pass.

### Icon Value Naming Conventions

| Set | Prefix | Example |
|-----|--------|---------|
| Lucide | `lucide-` | `lucide-home` |
| Simple Icons | `si-` | `si-github` |
| AWS | _(none)_ | `aws-lambda` |
| Devicon | `devicon-` | `devicon-javascript-original` |
| Phosphor | `phosphor-` | `phosphor-house` |
| Tabler | `tabler-` | `tabler-home`, `tabler-home-filled` |

AWS retains its existing unprefixed convention for backwards compatibility.

### Devicon Variants

Devicon ships multiple SVG variants per technology. All are included. Variant names are appended after the technology name with a hyphen, e.g.:
- `devicon-javascript-original`
- `devicon-javascript-plain`
- `devicon-javascript-line`
- `devicon-javascript-original-wordmark`

The glob pattern targets `devicon/icons/**/*.svg` and derives the value from the filename.

### Phosphor Variants

Only the `regular` weight is included. Component export names follow the pattern `House`, `Star`, `ArrowRight`, etc. from `@phosphor-icons/react`. Value format: `phosphor-{kebab-name}`.

### Tabler Variants

All Tabler exports are included. Filled variants are separate named exports (e.g., `IconHomeFilled`). The `Icon` prefix is stripped and the name is kebab-cased: `IconHome` → `tabler-home`, `IconHomeFilled` → `tabler-home-filled`.

---

## Picker Changes (`src/components/ui/icon-picker.tsx`)

- `IconSet` type becomes `string` (or a union of all set IDs) — driven by registry
- Initial state: `useState('lucide')`
- Tab buttons rendered from `iconRegistry.getSets()` — automatically alphabetical
- Icon grid rendered from the selected set's `icons` array (filtered by search query)
- No other behavioral changes

---

## Agent Manifest

`iconRegistry.toAgentManifest()` returns a compact JSON object describing all registered sets. This is designed to fit inside an LLM context window as part of a tool response or system prompt injection.

Example output:

```json
{
  "sets": [
    {
      "id": "lucide",
      "label": "Lucide",
      "description": "General purpose outline icons for UI elements",
      "valueFormat": "lucide-{name}",
      "examples": ["lucide-home", "lucide-settings", "lucide-user", "lucide-database"],
      "count": 1300
    },
    {
      "id": "devicon",
      "label": "Devicon",
      "description": "Technology and programming language icons, multiple style variants",
      "valueFormat": "devicon-{tech}-{variant}",
      "examples": ["devicon-python-original", "devicon-react-original", "devicon-postgresql-plain"],
      "count": 2400
    }
  ]
}
```

The future agent bridge will:
1. Accept entity context (name, description, type) from the UI
2. Embed the manifest in a prompt
3. Return a single `value` string (e.g. `"devicon-python-original"`)
4. The picker applies it directly via `onChange`

The UI bridge point (button in the picker to invoke the agent) is reserved for the follow-up implementation.

---

## Known Follow-Ups (Out of Scope)

- **Bundle optimization:** Phosphor and Tabler are bundled synchronously. Future work: migrate all sets to URL-based rendering + route-level code splitting for admin.
- **Agent integration:** UI trigger, backend endpoint, LLM prompt engineering.
- **Icon keywords:** `keywords` field on `IconEntry` is reserved but not populated in this pass.
