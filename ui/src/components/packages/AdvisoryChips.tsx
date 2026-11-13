import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { Advisory } from '@/types'

interface AdvisoryChipsProps {
  advisories: Advisory[]
}

const SEVERITY_VARIANTS: Record<string, BadgeProps['variant']> = {
  CRITICAL: 'danger',
  HIGH: 'danger',
  LOW: 'info',
  MEDIUM: 'warning',
}

/**
 * Advisory identifiers as linked chips. Each opens its own advisory in
 * a new window — the reader is mid-triage on a table and losing the
 * table to a navigation costs them their place. The CVE catalog's
 * severity follows the chip, and its description is the tooltip.
 */
export function AdvisoryChips({ advisories }: AdvisoryChipsProps) {
  if (advisories.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {advisories.map((advisory) => (
        <span className="inline-flex items-center gap-1" key={advisory.cve_id}>
          <a
            href={advisory.url}
            rel="noopener noreferrer"
            target="_blank"
            title={advisoryTooltip(advisory)}
          >
            <Badge className="font-mono text-[11px]" variant="danger">
              {advisory.cve_id}
            </Badge>
          </a>
          <SeverityBadge advisory={advisory} />
        </span>
      ))}
    </span>
  )
}

/** The CVE catalog severity and CVSS score, or nothing when unknown. */
export function SeverityBadge({ advisory }: { advisory: Advisory }) {
  if (!advisory.severity) return null
  const label =
    advisory.severity.charAt(0) + advisory.severity.slice(1).toLowerCase()
  return (
    <Badge
      className="text-[11px]"
      variant={SEVERITY_VARIANTS[advisory.severity] ?? 'neutral'}
    >
      {label}
      {advisory.cvss_score != null && ` ${advisory.cvss_score.toFixed(1)}`}
    </Badge>
  )
}

function advisoryTooltip(advisory: Advisory): string {
  return [advisory.title ?? advisory.cve_id, advisory.description]
    .filter(Boolean)
    .join('\n\n')
}
