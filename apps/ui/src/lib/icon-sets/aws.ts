import type {
  IconComponent,
  IconEntry,
  IconSetDefinition,
} from '@/lib/icon-registry'
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
  label: string
  url: string
}

function buildAwsIndex(): Record<string, AwsEntry> {
  const index: Record<string, AwsEntry> = {}
  for (const [path, url] of Object.entries(awsArchGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Arch_(.+)_64\.svg$/)
    if (!match) continue
    const raw = match[1]
    index[raw.toLowerCase()] = { label: raw.replace(/-/g, ' '), url }
  }
  for (const [path, url] of Object.entries(awsResGlob)) {
    const filename = path.split('/').pop()!
    const match = filename.match(/^Res_(.+)_48_Light\.svg$/)
    if (!match) continue
    const raw = match[1]
    const name = raw.replace(/_/g, '-').toLowerCase()
    index[name] = { label: raw.replace(/[_-]/g, ' '), url }
  }
  return index
}

const awsIndex = buildAwsIndex()
const awsIconNames = new Set(Object.keys(awsIndex))

export const AWS_ICONS: IconEntry[] = Object.entries(awsIndex)
  .map(([key, entry]) => ({ label: entry.label, value: key }))
  .sort((a, b) => a.label.localeCompare(b.label))

function resolve(value: string): IconComponent | null {
  if (!awsIconNames.has(value)) return null
  const url = resolveAwsUrl(value)
  return url ? createImgComponent(url) : null
}

function resolveAwsUrl(iconName: string): null | string {
  const key = iconName.toLowerCase()
  const direct = awsIndex[key]
  if (direct) return direct.url
  for (const [k, entry] of Object.entries(awsIndex)) {
    if (k.endsWith(key)) return entry.url
  }
  return null
}

function resolveUrl(value: string): null | string {
  if (!awsIconNames.has(value)) return null
  return resolveAwsUrl(value)
}

export const iconSet: IconSetDefinition = {
  description: 'Amazon Web Services architecture and resource icons',
  icons: AWS_ICONS,
  id: 'aws',
  label: 'AWS',
  resolve,
  resolveUrl,
  valueFormat: '{service-name}',
}
