import { createElement, useEffect, useState } from 'react'

import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'

// Lazy glob: returns `() => Promise<string>` per file. We avoid `eager: true`
// because that emits 1877 static `?import&url` imports, which floods the dev
// server (and Okteto proxy) on first picker open and leaves the index
// half-populated with broken `?import&url` URLs that the browser tries to
// render as <img>. Lazy mode bundles the SVGs in production while keeping
// dev imports on-demand.
const deviconLoaders = import.meta.glob<string>(
  '/node_modules/devicon/icons/**/*.svg',
  { import: 'default', query: '?url' },
)

// Build "devicon-<name>" → file path index synchronously from glob keys.
const pathByValue: Record<string, string> = {}
for (const path of Object.keys(deviconLoaders)) {
  const filename = path.split('/').pop()!
  const name = filename.replace('.svg', '')
  pathByValue[`devicon-${name}`] = path
}

// For the picker: one monochrome icon per tech, preferring -line over -plain.
const techVariants: Record<string, { line?: string; plain?: string }> = {}
for (const key of Object.keys(pathByValue)) {
  if (key.endsWith('-plain')) {
    const tech = key.slice(8, -6)
    if (!techVariants[tech]) techVariants[tech] = {}
    techVariants[tech].plain = key
  } else if (key.endsWith('-line')) {
    const tech = key.slice(8, -5)
    if (!techVariants[tech]) techVariants[tech] = {}
    techVariants[tech].line = key
  }
}

export const DEVICON_ICONS: IconEntry[] = Object.entries(techVariants)
  .map(([, variants]) => {
    const value = variants.line ?? variants.plain!
    const tech = value.slice(8).replace(/-plain$|-line$/, '')
    return { label: tech.replace(/-/g, ' '), value }
  })
  .sort((a, b) => a.label.localeCompare(b.label))

const urlCache = new Map<string, string>()
const inflight = new Map<string, Promise<string>>()

function createLazyDeviconImg(value: string): IconComponent {
  const Img: IconComponent = (props) => {
    const [url, setUrl] = useState<null | string>(
      () => urlCache.get(value) ?? null,
    )
    useEffect(() => {
      if (urlCache.has(value)) {
        setUrl(urlCache.get(value)!)
        return
      }
      let cancelled = false
      const promise = loadUrl(value)
      if (!promise) return
      promise.then((u) => {
        if (!cancelled) setUrl(u)
      })
      return () => {
        cancelled = true
      }
    }, [])
    if (!url) return null
    const { className, height, width, ...rest } = props as Record<
      string,
      unknown
    >
    return createElement('img', {
      alt: '',
      className,
      height: height ?? 16,
      src: url,
      style: { filter: 'brightness(0)' },
      width: width ?? 16,
      ...rest,
    })
  }
  return Img
}

function loadUrl(value: string): null | Promise<string> {
  const cached = urlCache.get(value)
  if (cached) return Promise.resolve(cached)
  const path = pathByValue[value]
  if (!path) return null
  const existing = inflight.get(value)
  if (existing) return existing
  const loader = deviconLoaders[path]
  if (!loader) return null
  const promise = loader().then((url) => {
    urlCache.set(value, url)
    inflight.delete(value)
    return url
  })
  inflight.set(value, promise)
  return promise
}

function resolve(value: string): IconComponent | null {
  if (!value.startsWith('devicon-')) return null
  if (!pathByValue[value]) return null
  return createLazyDeviconImg(value)
}

function resolveUrl(value: string): null | string {
  if (!value.startsWith('devicon-')) return null
  const cached = urlCache.get(value)
  if (cached) return cached
  // Kick off load so a later sync call can return the URL.
  void loadUrl(value)
  return null
}

export const iconSet: IconSetDefinition = {
  description:
    'Technology and programming language icons, multiple style variants',
  icons: DEVICON_ICONS,
  id: 'devicon',
  label: 'Devicon',
  resolve,
  resolveUrl,
  valueFormat: 'devicon-{tech}-{variant}',
}
