import { SEMVER_RE } from '@/lib/semver'
import type { TagFormat } from '@/types'

// A row in the version-format editor: a `TagFormat` plus display metadata and
// UI state (`enabled`, `builtin`, a stable `id`).
export interface FormatRow {
  builtin: boolean
  description: string
  enabled: boolean
  example: string
  id: string
  label: string
  pattern: string
}

// Built-in presets surfaced as toggleable rows in the version-format editor.
// Only `label`/`pattern` are persisted (as `TagFormat`); `description` and
// `example` are display-only metadata that lives here in the UI.
interface BuiltinFormat extends TagFormat {
  description: string
  example: string
}

const BUILTIN_FORMATS: BuiltinFormat[] = [
  {
    description:
      'MAJOR.MINOR.PATCH with optional pre-release and build metadata.',
    example: '2.11.5',
    label: 'Semantic versioning',
    pattern:
      '^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-([0-9A-Za-z-.]+))?(?:\\+([0-9A-Za-z-.]+))?$',
  },
  {
    description:
      'Year, month, and day with an optional suffix such as a build counter.',
    example: '2026.09.17-0',
    label: 'Calendar versioning',
    // Mirrors CALVER_TAG_PATTERN in imbi.common.versioning; keep in step.
    pattern: '^\\d{4}([.-])\\d{1,2}\\1\\d{1,2}(?:[.-]\\w+)?$',
  },
  {
    description: '7 to 40 character hexadecimal commit hash.',
    example: '7d4f2a3b',
    label: 'Git short SHA',
    pattern: '^[0-9a-f]{7,40}$',
  },
  {
    description: 'Accepts any non-empty string. Use as a catch-all.',
    example: 'nightly-build',
    label: 'Any format',
    pattern: '^.+$',
  },
]

const BUILTIN_BY_PATTERN = new Map(BUILTIN_FORMATS.map((f) => [f.pattern, f]))

// Earlier revisions of a built-in pattern, still stored on organizations and
// project types saved before the change. They render as that built-in row
// (toggled on) and are persisted with the current pattern on the next save.
const LEGACY_BUILTIN_PATTERNS = new Map<string, string>([
  ['^\\d{4}\\.\\d{1,2}(?:\\.\\d{1,2})?$', 'Calendar versioning'],
])

let rowSeq = 0

/**
 * Build the editor's working rows from a persisted `TagFormat[]`: every
 * built-in preset appears (toggled on when its pattern is present), and any
 * persisted pattern that isn't a built-in is appended as an enabled custom row.
 */
export function buildRows(formats: TagFormat[]): FormatRow[] {
  const enabled = new Set(
    formats.map((f) => builtinForPattern(f.pattern)?.pattern ?? f.pattern),
  )
  const rows: FormatRow[] = BUILTIN_FORMATS.map((b) => ({
    builtin: true,
    description: b.description,
    enabled: enabled.has(b.pattern),
    example: b.example,
    id: nextRowId(),
    label: b.label,
    pattern: b.pattern,
  }))
  for (const f of formats) {
    if (!builtinForPattern(f.pattern)) {
      rows.push({
        builtin: false,
        description: 'Custom version format.',
        enabled: true,
        example: '',
        id: nextRowId(),
        label: f.label,
        pattern: f.pattern,
      })
    }
  }
  return rows
}

/**
 * Whole-string match, mirroring the backend's `re.fullmatch` semantics so the
 * in-form tester agrees with server-side validation. Returns false for an
 * invalid pattern rather than throwing.
 */
export function fullMatch(pattern: string, value: string): boolean {
  try {
    return new RegExp(`^(?:${pattern})$`).test(value)
  } catch {
    return false
  }
}

/**
 * Whether ``tag`` satisfies the resolved tag-format policy. Mirrors the
 * backend's ``matches_tag_formats``, except that with no policy configured
 * the UI keeps requiring a semver-shaped tag rather than accepting anything.
 */
export function isTagAllowed(tag: string, formats: TagFormat[]): boolean {
  if (formats.length === 0) return SEMVER_RE.test(tag)
  return formats.some((f) => fullMatch(f.pattern, tag))
}

/** Return whether `pattern` is a valid (compilable) regular expression. */
export function isValidPattern(pattern: string): boolean {
  try {
    new RegExp(pattern)
    return true
  } catch {
    return false
  }
}

export function nextRowId(): string {
  rowSeq += 1
  return `vf-${rowSeq}`
}

/** The inline hint shown under a tag input the policy rejects. */
export function tagFormatHint(formats: TagFormat[]): string {
  if (formats.length === 0) return 'Use a semver tag, e.g. v6.5.2'
  const examples = formats
    .map((f) => BUILTIN_BY_PATTERN.get(f.pattern)?.example)
    .filter((e): e is string => !!e)
  const labels = formats.map((f) => f.label).join(' or ')
  return examples.length > 0
    ? `Use a ${labels} tag, e.g. ${examples.join(' or ')}`
    : `Use a ${labels} tag`
}

/** The enabled rows reduced to the persisted `TagFormat[]` shape. */
export function toFormats(rows: FormatRow[]): TagFormat[] {
  return rows
    .filter((r) => r.enabled)
    .map(({ label, pattern }) => ({ label, pattern }))
}

export function toggleAriaLabel(row: FormatRow): string {
  return row.enabled ? `Disable ${row.label}` : `Enable ${row.label}`
}

function builtinForPattern(pattern: string): BuiltinFormat | undefined {
  const legacyLabel = LEGACY_BUILTIN_PATTERNS.get(pattern)
  if (legacyLabel) return BUILTIN_FORMATS.find((f) => f.label === legacyLabel)
  return BUILTIN_BY_PATTERN.get(pattern)
}
