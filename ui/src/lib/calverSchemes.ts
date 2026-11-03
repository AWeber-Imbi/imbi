// Calendar-versioning schemes in calver.org notation, such as `YY.0M.MICRO`
// or `YYYY.0M.0D[.MICRO]`. Ports `calver_scheme_pattern` in
// `imbi.common.versioning` so the format editor can show and test the
// pattern before it is saved; keep the two in step. The API derives the
// stored pattern itself, so this copy only drives the editor.

const TOKENS: Record<string, string> = {
  '0D': '3[01]|[12]\\d|0[1-9]',
  '0M': '1[0-2]|0[1-9]',
  '0W': '5[0-3]|[1-4]\\d|0[1-9]',
  '0Y': '\\d{2}|[1-9]\\d{2}',
  D: '3[01]|[12]\\d|[1-9]',
  M: '1[0-2]|[1-9]',
  MICRO: '0|[1-9]\\d*',
  MINOR: '0|[1-9]\\d*',
  MODIFIER: '[0-9A-Za-z]+(?:\\.[0-9A-Za-z]+)*',
  W: '5[0-3]|[1-4]\\d|[1-9]',
  YY: '0|[1-9]\\d{0,2}',
  YYYY: '[1-9]\\d{3}',
}

// calver.org deprecated these spellings; they mean the unpadded tokens.
const ALIASES: Record<string, string> = { DD: 'D', MM: 'M', WW: 'W' }

const SCHEME_RE =
  /^(?<body>[0-9A-Z]+(?:[._-][0-9A-Z]+)*)(?:\[(?<sep>[._-])(?<optional>[0-9A-Z]+)\])?$/

interface Segment {
  optional: boolean
  sep: string
  token: string
}

/** The error message for an invalid `scheme`, or null when it is valid. */
export function schemeError(scheme: string): null | string {
  try {
    schemePattern(scheme)
    return null
  } catch (error) {
    return (error as Error).message
  }
}

/**
 * The regular expression for tags of a calver.org `scheme`. Throws an
 * `Error` whose message says what is wrong when the scheme is not valid.
 */
export function schemePattern(scheme: string): string {
  return parseScheme(scheme)
    .map((s, i) => {
      const part = `${escapeSep(s.sep)}(?P<t${i}>${TOKENS[s.token]})`
      return s.optional ? `(?:${part})?` : part
    })
    .reduce((pattern, part) => pattern + part, '^')
    .concat('$')
}

// Matches Python's `re.escape` for the three separators, so the pattern is
// the same text the API stores.
function escapeSep(sep: string): string {
  return sep === '.' || sep === '-' ? `\\${sep}` : sep
}

// fallow-ignore-next-line complexity
function parseScheme(scheme: string): Segment[] {
  const match = SCHEME_RE.exec(scheme.trim())
  if (!match?.groups) {
    throw new Error(
      'Use tokens such as YYYY, 0M, and MICRO separated by ".", "-", or "_", with an optional last segment in brackets, e.g. YYYY.0M.0D[.MICRO]',
    )
  }
  const parts = match.groups.body.split(/([._-])/)
  const segments: Segment[] = [{ optional: false, sep: '', token: parts[0] }]
  for (let i = 1; i < parts.length; i += 2) {
    segments.push({ optional: false, sep: parts[i], token: parts[i + 1] })
  }
  if (match.groups.optional) {
    segments.push({
      optional: true,
      sep: match.groups.sep,
      token: match.groups.optional,
    })
  }
  for (const s of segments) s.token = ALIASES[s.token] ?? s.token
  const tokens = segments.map((s) => s.token)
  const unknown = tokens.find((t) => !(t in TOKENS))
  if (unknown) throw new Error(`Unknown calver token ${unknown}`)
  if (new Set(tokens).size !== tokens.length) {
    throw new Error('A calver token can appear only once')
  }
  const has = (...names: string[]) => names.some((n) => tokens.includes(n))
  if (tokens.filter((t) => ['0Y', 'YY', 'YYYY'].includes(t)).length !== 1) {
    throw new Error('A calver scheme needs one year: YYYY, YY, or 0Y')
  }
  if (has('W', '0W') && has('M', '0M', 'D', '0D')) {
    throw new Error('Weeks cannot be combined with months or days')
  }
  if (has('D', '0D') && !has('M', '0M')) {
    throw new Error('A day needs a month')
  }
  for (const s of segments) {
    if (s.token === 'MODIFIER' && !s.optional) {
      throw new Error(
        'MODIFIER must be the optional last segment, e.g. [-MODIFIER]',
      )
    }
    if (s.optional && !['MICRO', 'MINOR', 'MODIFIER'].includes(s.token)) {
      throw new Error(
        'Only MINOR, MICRO, or MODIFIER can be the optional segment',
      )
    }
  }
  return segments
}
