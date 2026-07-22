import { useState } from 'react'

import { CircleCheck, CircleX } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { fullMatch } from '@/lib/versionFormats'
import type { TagFormat } from '@/types'

interface VersionTesterProps {
  formats: TagFormat[]
}

// Checks a candidate version against every enabled format and reports which
// accept it — mirrors the backend's "matches any configured format" rule.
export function VersionTester({ formats }: VersionTesterProps) {
  const [value, setValue] = useState('')

  const results = formats.map((f) => ({
    label: f.label,
    matched: !!value && fullMatch(f.pattern, value),
  }))
  const matchCount = results.filter((r) => r.matched).length

  return (
    <div>
      <h2 className="text-primary mt-8 text-base font-medium">
        Test a version string
      </h2>
      <p className="text-secondary mt-1 mb-3 text-sm">
        Check a version against every enabled format.
      </p>
      <div className="border-input rounded-lg border p-4">
        <Input
          className="max-w-90 font-mono text-sm"
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. 2.11.5"
          value={value}
        />
        {value ? (
          <VersionTesterResults matchCount={matchCount} results={results} />
        ) : (
          <div className="text-tertiary mt-4 text-sm">
            Enter a version to see which formats accept it.
          </div>
        )}
      </div>
    </div>
  )
}

function VersionTesterResults({
  matchCount,
  results,
}: {
  matchCount: number
  results: { label: string; matched: boolean }[]
}) {
  return (
    <>
      <div className="mt-4 flex max-w-md flex-col gap-2.5">
        {results.map((r, i) => (
          <div
            className="flex items-center justify-between"
            key={`${i}-${r.label}`}
          >
            <span className="text-secondary text-sm">{r.label}</span>
            {r.matched ? (
              <Badge variant="success">Match</Badge>
            ) : (
              <Badge variant="neutral">No match</Badge>
            )}
          </div>
        ))}
      </div>
      {matchCount > 0 ? (
        <div className="text-success mt-4 inline-flex items-center gap-1.5 text-sm">
          <CircleCheck className="size-4" />
          Accepted — {matchCount} {matchCount === 1 ? 'format' : 'formats'}.
        </div>
      ) : (
        <div className="text-danger mt-4 inline-flex items-center gap-1.5 text-sm">
          <CircleX className="size-4" />
          Rejected — no enabled format matches this version.
        </div>
      )}
    </>
  )
}
