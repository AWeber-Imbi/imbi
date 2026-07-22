// Pure helpers for @mention autocomplete, insertion, and rendering.
//
// The client resolves @mention selections to user *emails* and sends them in a
// `mentions: string[]` field (imbi-api #416/#417). The body text carries the
// human-readable `@Display Name` tokens; `mentions` carries the resolved
// emails. The backend never parses display names.

/** A candidate user for mention autocomplete. */
export interface MentionCandidate {
  display_name: string
  email: string
}

/** An in-progress @mention being typed: the query text and where the `@` sits. */
export interface MentionQuery {
  /** Index of the `@` in the textarea value. */
  start: number
  /** Text typed after the `@`, up to the caret. */
  text: string
}

interface Segment {
  email?: string
  text: string
  type: 'mention' | 'text'
}

const MAX_RESULTS = 6

/** Rank candidates for a query: case-insensitive substring on name or email. */
export function filterCandidates(
  candidates: MentionCandidate[],
  query: string,
): MentionCandidate[] {
  const q = query.trim().toLowerCase()
  const matches = candidates.filter(
    (c) =>
      c.display_name.toLowerCase().includes(q) ||
      c.email.toLowerCase().includes(q),
  )
  return matches.slice(0, MAX_RESULTS)
}

/**
 * Replace the open mention (from `query.start` to `caret`) with
 * `@Display Name ` and return the new value plus the caret position after it.
 */
export function insertMention(
  value: string,
  query: MentionQuery,
  caret: number,
  displayName: string,
): { caret: number; value: string } {
  const token = `@${displayName} `
  const next = value.slice(0, query.start) + token + value.slice(caret)
  return { caret: query.start + token.length, value: next }
}

/**
 * Detect an open @mention at the caret. Returns the query when the text
 * immediately before the caret is an `@` followed by mention-name characters
 * (letters, digits, spaces, dot, hyphen) with no intervening newline; null
 * otherwise. A trailing double-space closes the mention (the user moved on).
 */
export function mentionQueryAt(
  value: string,
  caret: number,
): MentionQuery | null {
  const before = value.slice(0, caret)
  const m = before.match(/@([\p{L}\p{N}.-]*(?: [\p{L}\p{N}.-]+)*)$/u)
  if (!m) return null
  // Don't trigger when the `@` is glued to a preceding word (e.g. an email).
  const at = caret - m[0].length
  const prev = at > 0 ? value[at - 1] : ''
  if (prev && !/\s/.test(prev)) return null
  return { start: at, text: m[1] }
}

/**
 * Split a comment body into plain-text and mention segments. A run of text is a
 * mention when it reads `@Display Name` for a known display name; the longest
 * matching name wins so "@Ada Lovelace" beats "@Ada". `mentions` (resolved
 * emails on the comment) is used to attach the email to the segment when the
 * display name is unambiguous.
 */
export function parseBody(
  body: string,
  knownNames: Map<string, string>,
): Segment[] {
  if (knownNames.size === 0) return [{ text: body, type: 'text' }]
  const lowerToEmail = new Map<string, string>()
  for (const [email, name] of knownNames) {
    lowerToEmail.set(name.toLowerCase(), email)
  }
  // Longest names first so a longer name isn't shadowed by a prefix.
  const names = [...knownNames.values()].sort((a, b) => b.length - a.length)
  const segments: Segment[] = []
  let i = 0
  let plainStart = 0
  // fallow-ignore-next-line complexity
  while (i < body.length) {
    const matched = body[i] === '@' && matchNameAt(body, i + 1, names)
    if (!matched) {
      i += 1
      continue
    }
    if (i > plainStart)
      segments.push({ text: body.slice(plainStart, i), type: 'text' })
    segments.push({
      email: lowerToEmail.get(matched.toLowerCase()),
      text: `@${matched}`,
      type: 'mention',
    })
    i += matched.length + 1
    plainStart = i
  }
  if (plainStart < body.length)
    segments.push({ text: body.slice(plainStart), type: 'text' })
  return segments
}

/**
 * Resolve the emails of every known display name mentioned in the body. Used to
 * derive the `mentions` array from the composed text at submit/edit time.
 */
export function resolveMentions(
  body: string,
  knownNames: Map<string, string>,
): string[] {
  const emails = new Set<string>()
  for (const segment of parseBody(body, knownNames)) {
    if (segment.type === 'mention' && segment.email) emails.add(segment.email)
  }
  return [...emails]
}

/** The longest display name that appears verbatim at `body[from..]`, or null. */
function matchNameAt(
  body: string,
  from: number,
  names: string[],
): null | string {
  for (const name of names) {
    if (body.startsWith(name, from)) {
      // Require a boundary so a short name doesn't match inside a longer word
      // (e.g. known "Ada" must not match "@Adam").
      const after = body[from + name.length]
      if (after === undefined || !/[\p{L}\p{N}.-]/u.test(after)) return name
    }
  }
  return null
}
