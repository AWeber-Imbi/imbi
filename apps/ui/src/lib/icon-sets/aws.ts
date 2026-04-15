import { iconRegistry } from '@/lib/icon-registry'
import type { IconComponent, IconEntry } from '@/lib/icon-registry'
import { createImgComponent } from '@/lib/icon-sets/utils'

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
