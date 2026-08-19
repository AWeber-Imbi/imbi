import { ApiError } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { extractApiErrorDetail } from '@/lib/apiError'

interface DispatchFailureNoticeProps {
  /** What the operator was trying to do, for the heading. */
  action: 'promote' | 'release'
  error: null | string
}

/**
 * The server's `detail` string for a refused dispatch, or `null`.
 *
 * Only for the statuses the API uses to *explain* a refusal — 4xx and
 * 502, each of which carries a sentence an operator can act on. A 5xx
 * that is not 502 is an Imbi bug with nothing useful in its body, and a
 * transport failure has no body at all; both keep the toast, which is the
 * right surface for "something broke" as opposed to "here is what to fix".
 */
export function dispatchFailureDetail(error: unknown): null | string {
  if (!(error instanceof ApiError)) return null
  if (error.status !== 502 && (error.status < 400 || error.status >= 500)) {
    return null
  }
  const detail = extractApiErrorDetail(error, '')
  // ``extractApiErrorDetail`` falls back to the ApiError's own synthetic
  // message ("HTTP 400: Bad Request") when the body carried nothing.
  // That is a status line, not an explanation, and pinning it to the form
  // would put a heading over no content.
  return detail && detail !== error.message ? detail : null
}

/**
 * Inline red strip carrying the server's refusal, verbatim.
 *
 * A refused cut or promote used to live in a Sonner toast. The API's
 * answers to a misconfigured Release workflow are two or three sentences
 * naming the workflow and the fix ("Correct the Release workflow option
 * on the integration, or clear it to cut the tag directly") — copy nobody
 * finishes reading in a corner toast that dismisses itself, which is how
 * a real user hit this and saw nothing discernible (Sentry IMBI-4T).
 *
 * Rendered where the failure happened and left there until the operator
 * changes something or tries again, so the sentence that names the fix is
 * still on screen while they act on it.
 */
export function DispatchFailureNotice({
  action,
  error,
}: DispatchFailureNoticeProps) {
  if (!error) return null
  const noun = action === 'promote' ? 'Promote' : 'Release'
  return (
    <Alert title={`${noun} refused`} variant="danger">
      <div className="flex flex-col gap-1.5">
        <span className="leading-relaxed">{error}</span>
        <span className="text-xs opacity-80">
          {action === 'promote'
            ? 'Nothing was dispatched.'
            : 'Nothing was dispatched — no tag was cut and no build started.'}
        </span>
      </div>
    </Alert>
  )
}
