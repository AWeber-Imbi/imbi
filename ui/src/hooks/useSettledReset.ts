import { useCallback, useEffect, useRef } from 'react'

interface ResettableMutation {
  isPending: boolean
  reset: () => void
}

/**
 * A stable `reset` for a TanStack mutation that waits out a request in
 * flight: called mid-request, it resets once the mutation settles.
 *
 * Resetting a pending mutation detaches its observer: `isPending` drops
 * to false mid-request (re-enabling the submit button) and the eventual
 * result or error never reaches the form. Callers clear a mutation's
 * standing refusal whenever the selection changes, which an operator can
 * do while a request is still running. Skipping that clear would leave
 * the request's answer -- a refusal for the commit it submitted -- to
 * stand against the commit picked since, so the clear is deferred to
 * settlement instead.
 *
 * The identity is stable as long as `reset` is (TanStack's is), so it is
 * safe in effect dependency lists.
 */
export function useSettledReset(mutation: ResettableMutation): () => void {
  const { isPending, reset } = mutation
  const pending = useRef(isPending)
  const deferred = useRef(false)
  useEffect(() => {
    pending.current = isPending
    if (!isPending && deferred.current) {
      deferred.current = false
      reset()
    }
  }, [isPending, reset])
  return useCallback(() => {
    if (pending.current) deferred.current = true
    else reset()
  }, [reset])
}
