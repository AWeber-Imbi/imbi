import { Badge } from '@/components/ui/badge'
import type { Advisory } from '@/types'

interface AdvisoryChipsProps {
  advisories: Advisory[]
}

/**
 * Advisory identifiers as linked chips. Each opens its own advisory in
 * a new window — the reader is mid-triage on a table and losing the
 * table to a navigation costs them their place.
 */
export function AdvisoryChips({ advisories }: AdvisoryChipsProps) {
  if (advisories.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {advisories.map((advisory) => (
        <a
          href={advisory.url}
          key={advisory.cve_id}
          rel="noopener noreferrer"
          target="_blank"
          title={advisory.title ?? advisory.cve_id}
        >
          <Badge className="font-mono text-[11px]" variant="danger">
            {advisory.cve_id}
          </Badge>
        </a>
      ))}
    </span>
  )
}
