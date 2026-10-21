import { useCallback, useEffect, useRef } from 'react'

interface ResettableMutation {
  isPending: boolean
  reset: () => void
}

/**
 * A stable `reset` for a TanStack mutation that does nothing while the
 * mutation is in flight.
 *
 * Resetting a pending mutation detaches its observer: `isPending` drops
 * to false mid-request (re-enabling the submit button) and the eventual
 * result or error never reaches the form. Callers clear a mutation's
 * standing refusal whenever the selection changes, which an operator can
 * do while a request is still running, so the clear must wait it out.
 *
 * The identity is stable as long as `reset` is (TanStack's is), so it is
 * safe in effect dependency lists.
 */
export function useSettledReset(mutation: ResettableMutation): () => void {
  const { isPending, reset } = mutation
  const pending = useRef(isPending)
  useEffect(() => {
    pending.current = isPending
  }, [isPending])
  return useCallback(() => {
    if (!pending.current) reset()
  }, [reset])
}
