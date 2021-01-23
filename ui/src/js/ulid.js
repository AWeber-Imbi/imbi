import { Ulid } from 'id128'

export function ulidAsUUID() {
  const value = Ulid.generate().toRaw().toLowerCase()
  return (
    value.substring(0, 8) +
    '-' +
    value.substring(8, 12) +
    '-' +
    value.substring(12, 16) +
    '-' +
    value.substring(16, 20) +
    '-' +
    value.substring(20, 32)
  )
}
