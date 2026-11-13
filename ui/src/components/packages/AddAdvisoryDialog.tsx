import { useEffect, useState } from 'react'

import { ShieldAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'

interface AddAdvisoryDialogProps {
  componentReleaseId: string
  isPending: boolean
  onOpenChange: (open: boolean) => void
  onRecord: (advisory: { cveId: string; title: string; url: string }) => void
  open: boolean
  version: string
}

/**
 * Records one advisory against a package version.
 *
 * Severity is deliberately not collected: it comes from the CVE
 * catalog when the advisory is shown. The URL and title are optional —
 * the API links an empty URL to the record on cve.org and fills an
 * empty title from the catalog.
 */
export function AddAdvisoryDialog({
  componentReleaseId,
  isPending,
  onOpenChange,
  onRecord,
  open,
  version,
}: AddAdvisoryDialogProps) {
  const [cveId, setCveId] = useState('')
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')

  useEffect(() => {
    if (open) {
      setCveId('')
      setUrl('')
      setTitle('')
    }
  }, [open, componentReleaseId])

  const trimmedUrl = url.trim()
  const urlValid = trimmedUrl.length === 0 || isHttpUrl(trimmedUrl)
  const ready = cveId.trim().length > 0 && urlValid
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldAlert className="text-danger size-4" />
            Record advisory
          </DialogTitle>
          <DialogDescription>
            Against version <span className="font-mono">{version}</span>. The
            same identifier recorded on another version links to one shared
            advisory.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 p-6">
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>
              Identifier
              <RequiredAsterisk />
            </span>
            <Input
              autoFocus
              onChange={(e) => setCveId(e.target.value)}
              placeholder="CVE-2025-1234"
              value={cveId}
            />
          </Label>
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>URL</span>
            <Input
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Empty: the record on cve.org"
              value={url}
            />
            {!urlValid && (
              <span className="text-danger">
                Enter a full http:// or https:// address.
              </span>
            )}
          </Label>
          <Label className="text-tertiary flex flex-col gap-1.5 text-xs">
            <span>Title</span>
            <Input
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Empty: the CVE catalog title"
              value={title}
            />
          </Label>
        </div>
        <DialogFooter>
          <Button
            onClick={() => onOpenChange(false)}
            type="button"
            variant="ghost"
          >
            Cancel
          </Button>
          <Button
            disabled={!ready || isPending}
            onClick={() =>
              onRecord({
                cveId: cveId.trim(),
                title: title.trim(),
                url: trimmedUrl,
              })
            }
            type="button"
          >
            Record
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * True only for an absolute http(s) URL.
 *
 * Both reports render the recorded value as the advisory chip's href,
 * so a scheme-less string becomes a dead link and a `javascript:` one
 * would run on click. The API rejects the same shapes; this keeps the
 * reader from finding out after the round trip.
 */
function isHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}
