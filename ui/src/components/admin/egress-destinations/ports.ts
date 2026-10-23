import type { EgressDestinationCreate } from '@/types'

type EgressPort = EgressDestinationCreate['ports'][number]

/** One port, with an optional protocol: `443`, `53/udp`. */
const PORT = /^(\d{1,5})(?:\/(tcp|udp))?$/i

export function formatPorts(ports: EgressPort[]): string {
  return ports.map((p) => `${p.port}/${p.protocol}`).join(', ')
}

/** The ports of a list such as `443, 53/udp`; null when one is not valid. */
export function parsePorts(value: string): EgressPort[] | null {
  const ports: EgressPort[] = []
  for (const token of value.split(/[\s,]+/).filter(Boolean)) {
    const match = PORT.exec(token)
    const port = Number(match?.[1])
    if (!match || port < 1 || port > 65535) return null
    ports.push({
      port,
      protocol: (match[2]?.toUpperCase() ?? 'TCP') as EgressPort['protocol'],
    })
  }
  return ports
}
