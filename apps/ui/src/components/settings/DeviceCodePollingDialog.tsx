import { useEffect, useRef, useState } from 'react'

import { CheckCircle2, ExternalLink, Loader2 } from 'lucide-react'

import { pollMyIdentity } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { IdentityPollingDescriptor } from '@/types'

interface DeviceCodePollingDialogProps {
  onComplete: () => void
  onDismiss: () => void
  open: boolean
  pluginLabel: string
  pluginSlug: string
  // Increment to nudge the modal to fire an immediate /poll tick
  // instead of waiting for the next interval.  Parent uses this when
  // the verification popup closes (strong signal that the user just
  // finished authorizing at the IdP).  Plain number — the IdP popup
  // is cross-origin, and passing a Window through React props blows
  // up React Refresh / DevTools when they try to read ``$$typeof``
  // on it (SecurityError).
  pokeNonce: number
  polling: IdentityPollingDescriptor | null
  // The signed state token returned by /start; the server uses it
  // to recover the IdP-issued device code on every poll tick.
  state: string
}

type DialogStatus = 'expired' | 'failed' | 'pending' | 'success'

export function DeviceCodePollingDialog({
  onComplete,
  onDismiss,
  open,
  pluginLabel,
  pluginSlug,
  pokeNonce,
  polling,
  state,
}: DeviceCodePollingDialogProps) {
  const [status, setStatus] = useState<DialogStatus>('pending')
  const [errorMessage, setErrorMessage] = useState<null | string>(null)
  // Refs avoid stale closures inside the polling timer.
  const cancelledRef = useRef(false)
  const onCompleteRef = useRef(onComplete)
  const stateRef = useRef(state)
  // Lets the popup-close watcher kick off an immediate /poll tick
  // instead of waiting for the next interval, so the table flips to
  // "Connected" the moment the user closes the verification window.
  const tickNowRef = useRef<() => void>(() => {})

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])
  useEffect(() => {
    stateRef.current = state
  }, [state])

  useEffect(() => {
    if (!open || !polling) {
      cancelledRef.current = true
      return
    }
    cancelledRef.current = false
    setStatus('pending')
    setErrorMessage(null)

    const intervalMs = Math.max(1, polling.interval) * 1000
    const startedAt = Date.now()
    const expiresInMs = polling.expires_in * 1000
    let timeoutId: null | ReturnType<typeof setTimeout> = null

    const tick = async () => {
      if (cancelledRef.current) return
      if (Date.now() - startedAt > expiresInMs) {
        setStatus('expired')
        return
      }
      try {
        const data = await pollMyIdentity(pluginSlug, stateRef.current)
        if (cancelledRef.current) return
        if (data.status === 'complete') {
          setStatus('success')
          // Brief success blink before the parent refreshes the list.
          window.setTimeout(() => {
            if (!cancelledRef.current) onCompleteRef.current()
          }, 600)
          return
        }
      } catch (err) {
        if (cancelledRef.current) return
        const detail = extractApiErrorDetail(err)
        if (
          typeof detail === 'string' &&
          detail.toLowerCase().includes('expired')
        ) {
          setStatus('expired')
          return
        }
        setStatus('failed')
        setErrorMessage(detail ?? 'Polling failed')
        return
      }
      timeoutId = setTimeout(tick, intervalMs)
    }

    // Expose a "fire a tick right now" hook for the popup-close
    // watcher below.  Clears any pending timer first so we don't
    // double-poll.
    tickNowRef.current = () => {
      if (timeoutId !== null) clearTimeout(timeoutId)
      timeoutId = null
      void tick()
    }

    // First tick fires immediately so the user gets feedback fast — AWS
    // also accepts polls before the user finishes authorizing.
    void tick()

    return () => {
      cancelledRef.current = true
      if (timeoutId !== null) clearTimeout(timeoutId)
      tickNowRef.current = () => {}
    }
  }, [open, polling, pluginSlug])

  // Parent bumps ``pokeNonce`` whenever the verification popup closes
  // — strong signal that the user just finished authorizing at the
  // IdP — so we can poll immediately instead of waiting up to
  // ``polling.interval`` seconds for the next scheduled tick.  The
  // initial value (0) is ignored.
  useEffect(() => {
    if (!open || !polling) return
    if (pokeNonce === 0) return
    tickNowRef.current()
  }, [open, polling, pokeNonce])

  // Belt-and-suspenders: also fire an immediate tick whenever the
  // parent tab regains focus or becomes visible.  Browsers throttle
  // setTimeout in background tabs, so any "the user came back" signal
  // is a better polling cue than the timer alone.
  useEffect(() => {
    if (!open || !polling) return
    const trigger = () => {
      if (!document.hidden) tickNowRef.current()
    }
    window.addEventListener('focus', trigger)
    document.addEventListener('visibilitychange', trigger)
    return () => {
      window.removeEventListener('focus', trigger)
      document.removeEventListener('visibilitychange', trigger)
    }
  }, [open, polling])

  if (!polling) return null

  const verificationHref =
    polling.verification_uri_complete ?? polling.verification_uri

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onDismiss()
      }}
      open={open}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Connect to {pluginLabel}</DialogTitle>
          <DialogDescription>
            Approve the request in the {pluginLabel} window. This page will
            update automatically once you finish.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 p-6">
          <div className="bg-muted/40 rounded-md border p-4">
            <div className="text-muted-foreground text-xs tracking-wide uppercase">
              Verification code
            </div>
            <div className="mt-1 font-mono text-2xl font-semibold tracking-widest select-all">
              {polling.user_code}
            </div>
          </div>

          <div className="text-sm">
            <span className="text-muted-foreground">Verification URL: </span>
            <a
              className="text-info break-all hover:underline"
              href={verificationHref}
              rel="noreferrer"
              target="_blank"
            >
              {verificationHref}
            </a>
          </div>

          <div className="flex items-center gap-2 text-sm">
            {status === 'pending' && (
              <>
                <Loader2 className="text-muted-foreground size-4 animate-spin" />
                <span className="text-muted-foreground">
                  Waiting for you to approve…
                </span>
              </>
            )}
            {status === 'success' && (
              <>
                <CheckCircle2 className="text-success size-4" />
                <span className="text-success">Connected.</span>
              </>
            )}
            {status === 'expired' && (
              <span className="text-destructive">
                The verification code expired. Close this dialog and try again.
              </span>
            )}
            {status === 'failed' && (
              <span className="text-destructive">
                {errorMessage ?? 'Polling failed.'}
              </span>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button asChild disabled={status === 'success'} variant="outline">
            <a href={verificationHref} rel="noreferrer" target="_blank">
              <ExternalLink className="mr-2 size-3.5" />
              Open {pluginLabel}
            </a>
          </Button>
          <Button onClick={onDismiss} variant="ghost">
            {status === 'success' ? 'Close' : 'Cancel'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
