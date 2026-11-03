import { Copy } from 'lucide-react'
import { toast } from 'sonner'

import { useClipboard } from '@/hooks/useClipboard'

/** A row id, shortened, that copies the full id to the clipboard. */
export function CopyId({ id }: { id: string }) {
  const { copy } = useClipboard()
  return (
    <button
      aria-label={`Copy id ${id}`}
      className="text-secondary hover:text-primary flex items-center gap-1 font-mono text-xs"
      onClick={() =>
        void copy(id).then((ok) =>
          ok
            ? toast.success('Id copied')
            : toast.error('Could not copy the id'),
        )
      }
      title={id}
      type="button"
    >
      {id.slice(0, 8)}
      <Copy className="size-3" />
    </button>
  )
}
