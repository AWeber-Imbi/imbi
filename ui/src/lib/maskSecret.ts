// If the value looks like a connection URL with embedded credentials
// (scheme://user:password@host…), mask only the password segment.
// Otherwise mask the whole value with bullets capped at a sensible length.
// For string_list values (comma-separated), each entry is masked
// independently so a list of URLs only hides each URL's password.
export function maskSecret(value: string): string {
  if (!value) return ''
  if (value.includes(',')) {
    return value
      .split(',')
      .map((part) => {
        // Preserve surrounding whitespace so the rendered list doesn't
        // shift when toggling reveal.
        const leading = part.match(/^\s*/)?.[0] ?? ''
        const trailing = part.match(/\s*$/)?.[0] ?? ''
        const inner = part.slice(leading.length, part.length - trailing.length)
        return leading + maskSecretSingle(inner) + trailing
      })
      .join(',')
  }
  return maskSecretSingle(value)
}

function maskSecretSingle(value: string): string {
  if (!value) return ''
  const url = /^([a-z][a-z0-9+\-.]*:\/\/)([^:@/\s]+):([^@/\s]+)(@.*)$/i.exec(
    value,
  )
  if (url) {
    return `${url[1]}${url[2]}:${'•'.repeat(8)}${url[4]}`
  }
  return '•'.repeat(Math.min(40, value.length || 8))
}
