import { Box, Container, type LucideIcon, Package } from 'lucide-react'

import type { Project } from '@/types'

export interface ArtifactInfo {
  icon: LucideIcon
  indexLabel: null | string
  indexUrl: null | string
  kind: 'container' | 'library' | 'unknown'
  // A copy-pasteable install/pull command, only when confidently derivable.
  pull: null | string
}

// Link-key substrings that identify a published-artifact index. The project
// has no explicit artifact metadata yet, so we infer from its links and hide
// artifact-specific affordances (pull command, index link) when we can't.
const CONTAINER_KEYS = ['ghcr', 'docker', 'container', 'image', 'registry']
const LIBRARY_KEYS = ['pypi', 'package', 'npm', 'rubygems', 'crates', 'maven']

/**
 * Best-effort artifact descriptor for the Releases tab.
 *
 * Returns ``kind: 'unknown'`` (generic icon, no pull command, no index link)
 * when the project carries no recognizable package/registry link — we never
 * fabricate an install command.
 */
export function deriveArtifact(
  project: Pick<Project, 'links' | 'name'>,
): ArtifactInfo {
  const container = findLink(project.links, CONTAINER_KEYS)
  if (container) {
    const path = stripScheme(container[1])
    return {
      icon: Container,
      indexLabel: 'Container image',
      indexUrl: container[1],
      kind: 'container',
      pull: path ? `docker pull ${path}` : null,
    }
  }
  const library = findLink(project.links, LIBRARY_KEYS)
  if (library) {
    const [key, url] = library
    const name = stripScheme(url).split('/').filter(Boolean).pop() ?? null
    const isNpm = key.toLowerCase().includes('npm')
    return {
      icon: Package,
      indexLabel: isNpm ? 'npm' : 'Package index',
      indexUrl: url,
      kind: 'library',
      pull: name
        ? isNpm
          ? `npm install ${name}`
          : `pip install ${name}`
        : null,
    }
  }
  return {
    icon: Box,
    indexLabel: null,
    indexUrl: null,
    kind: 'unknown',
    pull: null,
  }
}

function findLink(
  links: Record<string, string> | undefined,
  keys: string[],
): [string, string] | null {
  if (!links) return null
  for (const [key, url] of Object.entries(links)) {
    const k = key.toLowerCase()
    if (keys.some((needle) => k.includes(needle)) && url) return [key, url]
  }
  return null
}

function stripScheme(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/\/+$/, '')
}
